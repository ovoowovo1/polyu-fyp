from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict

from app.services.rag.orchestration import workflow_steps as adaptive_rag_workflow_steps

NodeFunc = Callable[[Dict[str, Any], Any], Awaitable[Dict[str, Any]]]


async def run_rag_workflow(
    question: str,
    state: Dict[str, Any],
    emit,
    events: asyncio.Queue[Dict[str, Any]],
    *,
    route_question_node: NodeFunc,
    retrieve_documents_node: NodeFunc,
    grade_documents_node: NodeFunc,
    retry_missing_concepts_node: NodeFunc,
    generate_answer_node: NodeFunc,
    grade_generation_node: NodeFunc,
    rewrite_query_node: NodeFunc,
    flush_events,
    make_event,
    build_result_payload,
    no_documents_answer: str,
    out_of_scope_answer: str,
    unsupported_result_reason: str,
    no_documents_result_reason: str,
    unreliable_result_reason: str,
    max_generation_retries: int,
    max_rewrite_attempts: int,
    max_missing_concept_retries: int,
    logger,
) -> AsyncGenerator[Dict[str, Any], None]:
    state = await route_question_node(state, emit)
    async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
        yield event

    if state.get("route_decision") == "reject":
        state["result_reason"] = unsupported_result_reason
        logger.info("[AdaptiveRAG] stream_end route_rejected result_reason=%s", state["result_reason"])
        yield adaptive_rag_workflow_steps.build_route_rejected_result(
            state=state,
            question=question,
            build_result_payload=build_result_payload,
            out_of_scope_answer=out_of_scope_answer,
        )
        return

    while True:
        state = await retrieve_documents_node(state, emit)
        async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
            yield event

        state = await grade_documents_node(state, emit)
        async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
            yield event

        if (
            state.get("missing_concepts")
            and state.get("missing_concept_retry_count", 0) < max_missing_concept_retries
        ):
            state["missing_concept_retry_count"] = state.get("missing_concept_retry_count", 0) + 1
            state = await retry_missing_concepts_node(state, emit)
            async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
                yield event
            state = await grade_documents_node(state, emit)
            async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
                yield event

        if state.get("filtered_documents"):
            state = await generate_answer_node(state, emit)
            async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
                yield event

            state = await grade_generation_node(state, emit)
            async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
                yield event

            if state.get("result_reason") != unreliable_result_reason:
                logger.info(
                    "[AdaptiveRAG] stream_end success answer_len=%s raw_sources=%s",
                    len(state.get("answer") or ""),
                    len(state.get("raw_sources", [])),
                )
                yield make_event("[generation] answer generation completed.", event_type="generation")
                yield adaptive_rag_workflow_steps.build_success_result(
                    state=state,
                    question=question,
                    build_result_payload=build_result_payload,
                    no_documents_answer=no_documents_answer,
                )
                return

            if state.get("generation_retry_count", 0) >= max_generation_retries:
                logger.warning(
                    "[AdaptiveRAG] stream_end generation_retry_limit reached retries=%s result_reason=%s",
                    state.get("generation_retry_count", 0),
                    state.get("result_reason"),
                )
                yield adaptive_rag_workflow_steps.build_generation_retry_limit_result(
                    state=state,
                    question=question,
                    build_result_payload=build_result_payload,
                    no_documents_answer=no_documents_answer,
                )
                return

            retry_count = adaptive_rag_workflow_steps.schedule_generation_retry(state)
            logger.info("[AdaptiveRAG] generation_retry scheduled retry_count=%s", retry_count)

        if (
            not state.get("filtered_documents")
            and state.get("missing_concepts")
            and state.get("missing_concept_retry_count", 0) >= max_missing_concept_retries
        ):
            state["result_reason"] = state.get("result_reason") or no_documents_result_reason
            yield adaptive_rag_workflow_steps.build_rewrite_limit_result(
                state=state,
                question=question,
                build_result_payload=build_result_payload,
                no_documents_answer=no_documents_answer,
                no_documents_result_reason=no_documents_result_reason,
            )
            return

        if state.get("rewrite_count", 0) >= max_rewrite_attempts:
            logger.warning(
                "[AdaptiveRAG] stream_end rewrite_limit reached rewrite_count=%s result_reason=%s",
                state.get("rewrite_count", 0),
                state.get("result_reason") or no_documents_result_reason,
            )
            yield adaptive_rag_workflow_steps.build_rewrite_limit_result(
                state=state,
                question=question,
                build_result_payload=build_result_payload,
                no_documents_answer=no_documents_answer,
                no_documents_result_reason=no_documents_result_reason,
            )
            return

        state = await rewrite_query_node(state, emit)
        async for event in adaptive_rag_workflow_steps.flush_pending_events(events, flush_events):
            yield event
