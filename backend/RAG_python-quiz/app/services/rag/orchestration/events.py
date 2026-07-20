from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Sequence

from app.services.rag.shared.helpers import build_raw_sources

EventCallback = Callable[[str, Any, str], Awaitable[None]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_event(message: str, data: Any = None, event_type: str = "progress") -> Dict[str, Any]:
    return {
        "type": event_type,
        "message": message,
        "data": data,
        "timestamp": utc_now(),
    }


def build_result_payload(
    *,
    state: Dict[str, Any],
    question: str,
    answer: str,
    answer_with_citations: List[Dict[str, Any]],
    raw_sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "type": "result",
        "question": question.strip(),
        "answer": answer,
        "answer_with_citations": answer_with_citations,
        "raw_sources": build_raw_sources(raw_sources),
        "result_reason": state.get("result_reason"),
        "timestamp": utc_now(),
    }


def initial_rag_state(
    question: str,
    selected_file_ids: Sequence[str],
    query_intent: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    stripped_question = question.strip()
    return {
        "question": stripped_question,
        "original_question": stripped_question,
        "selected_file_ids": list(selected_file_ids),
        "current_query": stripped_question,
        "classified_query": stripped_question,
        "rewrite_count": 0,
        "generation_retry_count": 0,
        "candidate_documents": [],
        "filtered_documents": [],
        "query_intent": query_intent or {},
        "planner_result": {},
        "covered_concepts": [],
        "missing_concepts": [],
        "missing_concept_retry_count": 0,
        "grading_failed": False,
        "route_reason": "",
        "answer": "",
        "citations": [],
        "answer_with_citations": [],
        "raw_sources": [],
        "evidence_nodes": [],
        "result_reason": None,
    }


def make_queue_emit(events: asyncio.Queue[Dict[str, Any]]) -> EventCallback:
    async def emit(message: str, data: Any = None, event_type: str = "retrieval") -> None:
        await events.put(make_event(message, data, event_type))

    return emit


async def flush_events(events: asyncio.Queue[Dict[str, Any]]) -> AsyncGenerator[Dict[str, Any], None]:
    while not events.empty():
        event = await events.get()
        yield event
        events.task_done()
