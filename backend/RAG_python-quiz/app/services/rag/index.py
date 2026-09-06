"""Public RAG entry point: retrieval, one evidence draft, validation, bounded repair."""
from __future__ import annotations

import asyncio
import contextlib
from pydantic import ValidationError
import time
from uuid import uuid4

from app.logger import get_logger
from app.utils.model_usage import usage_scope
from app.services.rag.language import answer_language, system_messages, notice
from app.services.ai.llm.structured_json import generate_structured_json
from app.services.rag.citation.models import AnswerDraft
from app.services.rag.citation.service import generate_answer, verify_answer, result_payload
from app.services.rag.orchestration.events import make_event
from app.services.rag.orchestration.routing import plan_question
from app.services.rag.retrieval.context import build_context
from app.services.rag.retrieval.service import retrieve_documents_node, grade_documents_node, retry_missing_concepts_node
from app.services.rag.retrieval.workflow import build_initial_state

logger = get_logger(__name__)


def unavailable(question: str, trace_id: str, *, service_failure: bool = False) -> dict:
    message = notice("verification_unavailable" if service_failure else "insufficient_evidence")
    return result_payload(AnswerDraft(blocks=[], limitations=[message]), [], {}, [], trace_id, question)


async def run_rag(question: str, selected_file_ids: list[str], emit, *, trace: dict | None = None) -> dict:
    trace = trace if trace is not None else {}
    trace_id = str(uuid4())
    trace.update(trace_id=trace_id, stages=[])
    started = time.monotonic()
    language_token = answer_language.set(None)
    messages_token = system_messages.set(None)
    usage = usage_scope(trace_id, label="RAGUsage")
    usage.__enter__()
    stage = "planning"

    def record(stage: str, documents: list[dict], **details):
        entry = {"stage": stage, "chunks": [{"chunk_id": d["chunkId"],
                 "file_id": d["fileId"], "concepts": d.get("covered_concepts", []),
                 "reason": d.get("grading_reason"), "score": d.get("relevance_score", d.get("rrf_score"))}
                for d in documents], **details}
        trace["stages"].append(entry)
        logger.info("[RAG] trace_id=%s diagnostic=%s", trace_id, entry)

    try:
        if not selected_file_ids:
            return unavailable(question, trace_id)
        planner = await plan_question(question, generate_structured_json=generate_structured_json, logger=logger)
        answer_language.set(planner.get("answer_language"))
        system_messages.set(planner.get("messages"))
        if planner["decision"] == "reject":
            return unavailable(question, trace_id)
        state = build_initial_state(question, selected_file_ids, planner["query_intent"])
        stage = "retrieval"
        state = await retrieve_documents_node(state, emit)
        record("retrieved", state["candidate_documents"])
        stage = "grading"
        state = await grade_documents_node(state, emit)
        record("graded", state["filtered_documents"], grades=state.get("grading_diagnostics", []))
        if state["grading_failed"]:
            return unavailable(question, trace_id, service_failure=True)
        required = planner["query_intent"]["required_concepts"]
        stage = "context"
        documents = await build_context(state["filtered_documents"], selected_file_ids, required)
        record("context", documents)
        draft, verdict, errors = None, None, {}
        if documents:
            await emit("Generating an evidence-grounded answer…", None, "generation")
            stage = "generation"
            draft = await generate_answer(question, documents)
            stage = "evidence_verification"
            verdict, errors = await verify_answer(question, draft, documents, selected_file_ids)
        missing = list(dict.fromkeys(state["missing_concepts"] + (verdict.missing_topics if verdict else [])))
        if missing:
            state["query_intent"]["required_concepts"] = list(dict.fromkeys(required + missing))
            state["missing_concepts"] = missing
            stage = "retry_retrieval"
            state = await retry_missing_concepts_node(state, emit)
            record("retry_retrieved", state["candidate_documents"])
            stage = "retry_grading"
            state = await grade_documents_node(state, emit)
            record("retry_graded", state["filtered_documents"], grades=state.get("grading_diagnostics", []))
            if state["grading_failed"]:
                return unavailable(question, trace_id, service_failure=True)
            stage = "retry_context"
            documents = await build_context(state["filtered_documents"], selected_file_ids, state["query_intent"]["required_concepts"])
            record("retry_context", documents)
        if not documents:
            return unavailable(question, trace_id)
        if draft is None or errors or missing:
            await emit("Checking missing evidence and repairing the answer…", None, "generation")
            stage = "repair"
            draft = await generate_answer(question, documents, feedback={
                "previous": draft.model_dump() if draft else None, "errors": errors, "missing_topics": missing})
            stage = "repair_verification"
            verdict, errors = await verify_answer(question, draft, documents, selected_file_ids)
        stage = "result"
        result = result_payload(draft, documents, errors, verdict.missing_topics, trace_id, question)
        record("cited", [d for d in documents if d["chunkId"] in {s["chunk_id"] for s in result["sources"]}],
               rejected_blocks=errors, status=result["status"])
        return result
    except Exception as error:
        fields = []
        if isinstance(error, ValidationError):
            stage = {"generation": "answer_parsing", "repair": "repair_parsing"}.get(stage, stage)
            fields = [{"location": item["loc"], "type": item["type"]}
                      for item in error.errors(include_input=False, include_context=False, include_url=False)]
        logger.error("[RAG] trace_id=%s stage=%s error_type=%s fields=%s",
                     trace_id, stage, type(error).__name__, fields)
        return unavailable(question, trace_id, service_failure=True)
    finally:
        usage.__exit__(None, None, None)
        answer_language.reset(language_token)
        system_messages.reset(messages_token)
        trace["latency_seconds"] = time.monotonic() - started
        logger.info("[RAG] trace_id=%s latency_seconds=%.3f", trace_id, trace["latency_seconds"])


async def run_adaptive_rag_stream(question: str, selected_file_ids: list[str]):
    queue = asyncio.Queue()

    async def emit(message, data=None, event_type="retrieval"):
        await queue.put(make_event(message, data, event_type))

    async def work():
        result = await run_rag(question.strip(), selected_file_ids, emit)
        await queue.put({"type": "result", **result})

    task = asyncio.create_task(work())
    try:
        while True:
            event = await queue.get()
            yield event
            if event["type"] == "result":
                break
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
