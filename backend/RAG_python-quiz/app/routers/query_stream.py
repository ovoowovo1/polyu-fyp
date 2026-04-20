from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.logger import get_logger
from app.services import pg_service
from app.services.ai_service import generate_answer_with_langchain
from app.services.vector_query_service import retrieve_vector_context

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["query"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_progress(message: str, data=None, event_type: str = "progress") -> bytes:
    payload = {
        "type": event_type,
        "message": message,
        "data": data,
        "timestamp": _utc_now(),
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _retrieve_vector_context(question: str, selected_file_ids: List[str]) -> tuple[List[dict], str]:
    return await retrieve_vector_context(
        question,
        selected_file_ids,
        k=20,
        log_prefix="vector retrieval",
    )


def _reciprocal_rank_fusion(results_list: List[List[dict]], k: int = 60) -> List[dict]:
    rrf_scores: dict[str, dict] = {}

    for results in results_list:
        if not results:
            continue

        for rank, doc in enumerate(results, start=1):
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            score = 1.0 / (k + rank)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {
                    "doc": doc,
                    "rrf_score": 0.0,
                }
            rrf_scores[chunk_id]["rrf_score"] += score

    sorted_docs = sorted(rrf_scores.values(), key=lambda item: item["rrf_score"], reverse=True)
    return [{**item["doc"], "rrf_score": round(item["rrf_score"], 4)} for item in sorted_docs]


async def sse_event_stream(question: str, selected_file_ids: List[str]) -> AsyncGenerator[bytes, None]:
    yield _make_progress("Starting retrieval...", {"question": question})

    if not selected_file_ids:
        yield _make_progress("Please select at least one document for retrieval.")
        return

    event_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def enqueue_progress(message: str, data=None, event_type: str = "progress") -> None:
        await event_queue.put(_make_progress(message, data, event_type))

    async def run_graph_search() -> List[dict]:
        await enqueue_progress(
            "[graph retrieval] graph search is currently disabled; skipping.",
            0,
            event_type="graph",
        )
        return []

    async def run_vector_search() -> List[dict]:
        try:
            await enqueue_progress("[vector retrieval] generating query vector...", event_type="vectorProgress")
            vector_results, retrieval_mode = await _retrieve_vector_context(question, selected_file_ids)
            if retrieval_mode == "fallback":
                await enqueue_progress(
                    "[vector retrieval] primary embedding failed; retried with standby embedding model.",
                    event_type="vectorProgress",
                )
            await enqueue_progress("[vector retrieval] retrieving vectors from database...", event_type="vectorProgress")
            await enqueue_progress(
                f"[vector retrieval] completed. Found {len(vector_results)} relevant results.",
                len(vector_results),
                event_type="vector",
            )
            return vector_results
        except Exception as err:
            logger.error("[vector retrieval] error occurred: %s", err)
            await enqueue_progress(f"[vector retrieval] error occurred: {err}", 0, event_type="vector")
            return []

    async def run_fulltext_search() -> List[dict]:
        try:
            await enqueue_progress("[fulltext retrieval] executing fulltext search...", event_type="fulltextProgress")
            fulltext_results = await asyncio.to_thread(
                pg_service.retrieve_context_by_keywords,
                question,
                selected_file_ids,
            )
            await enqueue_progress(
                f"[fulltext retrieval] completed. Found {len(fulltext_results)} relevant results.",
                len(fulltext_results),
                event_type="fulltext",
            )
            return fulltext_results
        except Exception as err:
            await enqueue_progress(f"[fulltext retrieval] error occurred: {err}", 0, event_type="fulltext")
            return []

    graph_task = asyncio.create_task(run_graph_search())
    vector_task = asyncio.create_task(run_vector_search())
    fulltext_task = asyncio.create_task(run_fulltext_search())

    while True:
        if graph_task.done() and vector_task.done() and fulltext_task.done() and event_queue.empty():
            break
        try:
            event = event_queue.get_nowait()
            yield event
            event_queue.task_done()
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.02)

    graph_results = graph_task.result() if not graph_task.cancelled() else []
    vector_results = vector_task.result() if not vector_task.cancelled() else []
    fulltext_results = fulltext_task.result() if not fulltext_task.cancelled() else []

    initial_docs = _reciprocal_rank_fusion([graph_results, vector_results, fulltext_results], k=60)
    yield _make_progress(
        f"RRF fusion completed. Obtained {len(initial_docs)} candidate documents.",
        len(initial_docs),
        event_type="merge",
    )

    if not initial_docs:
        result_payload = {
            "type": "result",
            "question": question,
            "answer": "Sorry, no relevant information was found in the specified documents.",
            "answer_with_citations": [],
            "raw_sources": [],
            "timestamp": _utc_now(),
        }
        yield (json.dumps(result_payload) + "\n").encode("utf-8")
        return

    formatted_context = []
    file_ids = []
    chunk_ids = []
    for idx, doc in enumerate(initial_docs, start=1):
        content = doc.get("content") or doc.get("text")
        source_info = (
            f"source_file: \"{doc.get('source')}\", "
            f"page_number: \"{doc.get('page')}\", "
            f"file_id: \"{doc.get('fileId')}\", "
            f"file_chunk_id: \"{doc.get('chunkId')}\""
        )
        formatted_context.append(f"[Document {idx}]\n{source_info}\nContent:\n\"\"\"\n{content}\n\"\"\"")
        file_ids.append(doc.get("fileId"))
        chunk_ids.append(doc.get("chunkId"))

    yield _make_progress("[AI response] generating answer...", event_type="aiProgress")
    ai_response = await generate_answer_with_langchain(
        "\n\n".join(formatted_context),
        question.strip(),
        file_ids,
        chunk_ids,
    )
    logger.debug("AI response: %s", ai_response)

    sources = [
        {
            "content": (doc.get("content") or doc.get("text")),
            "source": doc.get("source") or "Unknown source",
            "pageNumber": doc.get("page") or "Unknown page",
            "score": doc.get("score") or doc.get("relevance_score"),
            "fileId": doc.get("fileId"),
            "chunkId": doc.get("chunkId"),
        }
        for doc in initial_docs
    ]

    yield _make_progress("[AI response] completed.", event_type="aiProgress")
    result_payload = {
        "type": "result",
        "question": question.strip(),
        "answer": ai_response.get("answer"),
        "answer_with_citations": ai_response.get("answer_with_citations") or [],
        "raw_sources": sources,
        "timestamp": _utc_now(),
    }
    yield (json.dumps(result_payload) + "\n").encode("utf-8")


@router.post("/query-stream")
async def query_stream(request: Request):
    body = await request.json()
    question = (body.get("question") or "").strip()
    selected_file_ids = body.get("selectedFileIds") or []
    if not question:
        raise HTTPException(status_code=400, detail={"error": "Please provide a query question"})
    if len(selected_file_ids) == 0:
        raise HTTPException(status_code=400, detail={"error": "Please select at least one document for retrieval"})

    return StreamingResponse(sse_event_stream(question, selected_file_ids), media_type="text/plain; charset=utf-8")
