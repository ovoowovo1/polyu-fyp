from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, TypedDict


class AdaptiveRAGState(TypedDict, total=False):
    question: str
    original_question: str
    selected_file_ids: List[str]
    current_query: str
    classified_query: str
    planner_result: Dict[str, Any]
    route_decision: str
    route_reason: str
    rewrite_count: int
    generation_retry_count: int
    missing_concept_retry_count: int
    grading_failed: bool
    candidate_documents: List[Dict[str, Any]]
    filtered_documents: List[Dict[str, Any]]
    query_intent: Dict[str, Any]
    covered_concepts: List[str]
    missing_concepts: List[str]
    answer: str
    citations: List[Dict[str, Any]]
    answer_with_citations: List[Dict[str, Any]]
    raw_sources: List[Dict[str, Any]]
    evidence_nodes: List[Dict[str, Any]]
    result_reason: str


EventCallback = Callable[[str, Any, str], Awaitable[None]]
