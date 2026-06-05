from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, TypedDict

from app.services.rag.retrieval_intent import QueryIntent


class AdaptiveRetrievalState(TypedDict, total=False):
    question: str
    original_question: str
    selected_file_ids: List[str]
    current_query: str
    rewrite_count: int
    candidate_documents: List[Dict[str, Any]]
    filtered_documents: List[Dict[str, Any]]
    retrieval_mode_summary: Dict[str, Any]
    vector_retrieval_degraded: bool
    fallback_reason: str | None
    query_intent: QueryIntent
    covered_concepts: List[str]
    missing_concepts: List[str]


class AdaptiveRetrievalResult(TypedDict, total=False):
    documents: List[Dict[str, Any]]
    candidate_documents: List[Dict[str, Any]]
    rewrite_count: int
    current_query: str
    fallback_reason: str | None
    retrieval_mode_summary: Dict[str, Any]
    vector_retrieval_degraded: bool
    query_intent: QueryIntent
    covered_concepts: List[str]
    missing_concepts: List[str]


EventCallback = Callable[[str, Any, str], Awaitable[None]]
