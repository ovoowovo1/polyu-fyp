from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence


ConceptNormalizer = Callable[[str], str]
EventCallback = Callable[[str, Any, str], Awaitable[None]]


def _default_normalize_concept(value: str) -> str:
    return " ".join((value or "").strip().strip("?.!,:;").split())


def normalize_concepts(
    concepts: Sequence[str],
    *,
    normalizer: ConceptNormalizer | None = None,
) -> List[str]:
    normalize_one = normalizer or _default_normalize_concept
    seen: set[str] = set()
    unique: List[str] = []
    for concept in concepts:
        normalized = normalize_one(concept or "")
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def normalize_doc(
    doc: Dict[str, Any],
    *,
    normalize_concept_fields: Sequence[str] = (),
    concept_normalizer: ConceptNormalizer | None = None,
) -> Dict[str, Any]:
    text = (doc.get("content") or doc.get("text") or "").strip()
    normalized = {
        **doc,
        "text": text,
        "content": text,
        "source": doc.get("source") or doc.get("document_name") or "Unknown source",
        "page": (
            doc.get("page")
            or doc.get("pageNumber")
            or doc.get("page_start")
            or doc.get("pageStart")
            or "Unknown page"
        ),
        "fileId": doc.get("fileId") or doc.get("fileid"),
        "chunkId": doc.get("chunkId") or doc.get("chunkid"),
    }
    for field in normalize_concept_fields:
        if field in doc:
            normalized[field] = normalize_concepts(doc.get(field, []), normalizer=concept_normalizer)
    return normalized


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def build_raw_sources(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "content": normalized.get("content") or "",
            "source": normalized.get("source") or "Unknown source",
            "pageNumber": normalized.get("page") or "Unknown page",
            "score": _float_or_none(
                normalized.get("score") or normalized.get("relevance_score") or normalized.get("rrf_score")
            ),
            "fileId": normalized.get("fileId"),
            "chunkId": normalized.get("chunkId"),
        }
        for normalized in (normalize_doc(doc) for doc in documents)
    ]


def build_evidence_nodes(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw_sources = build_raw_sources(documents)
    return [
        {
            "node_id": doc.get("chunkId") or f"evidence-node-{index}",
            "file_id": doc.get("fileId"),
            "chunk_id": doc.get("chunkId"),
            "source": doc.get("source") or "Unknown source",
            "page": doc.get("pageNumber") or "Unknown page",
            "text": doc.get("content") or "",
            "score": doc.get("score"),
        }
        for index, doc in enumerate(raw_sources, start=1)
    ]


def build_retrieval_evidence(
    documents: Sequence[Dict[str, Any]],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
    concept_normalizer: ConceptNormalizer | None = None,
) -> Dict[str, Any]:
    required = normalize_concepts(required_concepts, normalizer=concept_normalizer)
    covered = normalize_concepts(covered_concepts, normalizer=concept_normalizer)
    if not covered:
        derived: List[str] = []
        for doc in documents:
            derived.extend(doc.get("covered_concepts", []))
        covered = normalize_concepts(derived, normalizer=concept_normalizer)
    missing = [concept for concept in required if concept not in covered]
    return {
        "raw_sources": build_raw_sources(documents),
        "evidence_nodes": build_evidence_nodes(documents),
        "required_concepts": required,
        "covered_concepts": covered,
        "missing_concepts": missing,
    }


async def safe_emit(
    callback: EventCallback,
    message: str,
    data: Any = None,
    event_type: str = "retrieval",
) -> None:
    await callback(message, data, event_type)
