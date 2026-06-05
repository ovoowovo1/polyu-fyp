from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class EvidenceCitation(TypedDict):
    chunk_id: str
    file_id: Optional[str]
    source: str
    page: Any


class EvidenceSource(TypedDict):
    content: str
    source: str
    pageNumber: Any
    score: Optional[float]
    fileId: Optional[str]
    chunkId: Optional[str]


class EvidenceNode(TypedDict):
    node_id: str
    file_id: Optional[str]
    chunk_id: Optional[str]
    source: str
    page: Any
    text: str
    score: Optional[float]


class CitationEvidenceResult(TypedDict):
    answer_text: str
    citations: List[EvidenceCitation]
    raw_sources: List[EvidenceSource]
    evidence_nodes: List[EvidenceNode]
    answer_with_citations: List[Dict[str, Any]]
    required_concepts: List[str]
    covered_concepts: List[str]
    missing_concepts: List[str]
    coverage_status: str
