from __future__ import annotations

from typing import Any, Dict


async def flush_pending_events(events, flush_events):
    async for event in flush_events(events):
        yield event


def build_route_rejected_result(
    *,
    state: Dict[str, Any],
    question: str,
    build_result_payload,
    out_of_scope_answer: str,
) -> Dict[str, Any]:
    return build_result_payload(
        state=state,
        question=question,
        answer=out_of_scope_answer,
        answer_with_citations=[],
        raw_sources=[],
    )


def build_success_result(
    *,
    state: Dict[str, Any],
    question: str,
    build_result_payload,
    no_documents_answer: str,
) -> Dict[str, Any]:
    return build_result_payload(
        state=state,
        question=question,
        answer=state.get("answer") or no_documents_answer,
        answer_with_citations=state.get("answer_with_citations", []),
        raw_sources=state.get("raw_sources", []),
    )


def build_generation_retry_limit_result(
    *,
    state: Dict[str, Any],
    question: str,
    build_result_payload,
    no_documents_answer: str,
) -> Dict[str, Any]:
    return build_result_payload(
        state=state,
        question=question,
        answer=no_documents_answer,
        answer_with_citations=[],
        raw_sources=state.get("raw_sources", []),
    )


def schedule_generation_retry(state: Dict[str, Any]) -> int:
    state["generation_retry_count"] = state.get("generation_retry_count", 0) + 1
    return state["generation_retry_count"]


def build_rewrite_limit_result(
    *,
    state: Dict[str, Any],
    question: str,
    build_result_payload,
    no_documents_answer: str,
    no_documents_result_reason: str,
) -> Dict[str, Any]:
    state["result_reason"] = state.get("result_reason") or no_documents_result_reason
    return build_result_payload(
        state=state,
        question=question,
        answer=no_documents_answer,
        answer_with_citations=[],
        raw_sources=state.get("raw_sources", []),
    )
