from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypedDict

from app.logger import get_logger
from app.services import pg_service
from app.services.ai_service import generate_structured_json
from app.services.rag_shared import normalize_concepts, normalize_doc, safe_emit
from app.services.vector_query_service import is_retryable_embedding_error, retrieve_vector_context

logger = get_logger(__name__)

MAX_DOCS_TO_GRADE = 8
MAX_REWRITE_ATTEMPTS = 1
RETRIEVAL_K = 20
RRF_K = 60
MAX_DOC_PREVIEW_CHARS = 1800
DOCUMENT_GRADING_CONCURRENCY: int | None = None
NO_RELEVANT_DOCUMENTS_FALLBACK_REASON = "no_relevant_documents"
EMPTY_SELECTION_FALLBACK_REASON = "empty_selection"
RESERVED_CANDIDATES_PER_SUBQUERY = 2
_MULTI_CONCEPT_SPLIT_RE = re.compile(r"\s*(?:/|,|\band\b|\bvs\.?\b|\bversus\b)\s*", re.IGNORECASE)
_COMPARISON_HEAD_PATTERNS = [
    re.compile(r"^(?:what\s+is|what's)\s+(?:the\s+)?(?:difference|differences|different)\s+(?:between|in)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:the\s+)?(?:difference|differences|different)\s+(?:between|in)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:compare|contrast)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:comparison)\s+(?:between|of)\s+(.+)$", re.IGNORECASE),
]
_DEFINITION_HEAD_PATTERN = re.compile(r"^(?:what\s+is|what\s+are|define|explain)\s+(.+)$", re.IGNORECASE)
_LEADING_NOISE_RE = re.compile(
    r"^(?:the\s+)?(?:difference|differences|different|comparison|compare|contrast)\s+(?:between|in|of)\s+",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+", re.IGNORECASE)
_GENERIC_CONCEPT_TOKENS = {
    "a",
    "an",
    "and",
    "database",
    "databases",
    "db",
    "dbs",
    "in",
    "language",
    "languages",
    "of",
    "system",
    "systems",
    "the",
}


class QuerySearchSpec(TypedDict):
    label: str
    query: str
    concept: Optional[str]
    query_kind: str


class QueryIntent(TypedDict):
    mode: str
    intent_type: str
    required_concepts: List[str]
    subqueries: List[QuerySearchSpec]
    search_queries: List[QuerySearchSpec]


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


async def _safe_emit(callback: EventCallback, message: str, data: Any = None, event_type: str = "retrieval") -> None:
    await safe_emit(callback, message, data, event_type)


def _canonicalize_known_concept(concept: str) -> str:
    lowered = _NON_ALNUM_RE.sub(" ", (concept or "").casefold())
    tokens = [token for token in lowered.split() if token not in _GENERIC_CONCEPT_TOKENS]
    if tokens == ["sql"]:
        return "SQL"
    if tokens in (["nosql"], ["no", "sql"]):
        return "NoSQL"
    if tokens == ["newsql"]:
        return "NewSQL"
    return re.sub(r"\s+", " ", (concept or "").strip())


def _clean_concept_fragment(fragment: str) -> str:
    cleaned = re.sub(r"\s+", " ", (fragment or "").strip().strip("?.!,:;")).strip()
    cleaned = _LEADING_NOISE_RE.sub("", cleaned)
    cleaned = re.sub(r"^(?:between|in|of)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = _LEADING_ARTICLE_RE.sub("", cleaned)
    return _canonicalize_known_concept(cleaned)


def _normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_doc(
        doc,
        normalize_concept_fields=("retrieved_for_concepts", "covered_concepts"),
        concept_normalizer=_normalize_concept_label,
    )


def _normalize_concept_label(concept: str) -> str:
    return _clean_concept_fragment(concept)


def _unique_in_order(values: Sequence[str]) -> List[str]:
    return normalize_concepts(values, normalizer=_normalize_concept_label)


def _extract_comparison_tail(question: str) -> str:
    cleaned = " ".join((question or "").split())
    for pattern in _COMPARISON_HEAD_PATTERNS:
        match = pattern.match(cleaned)
        if match:
            return match.group(1)
    if re.search(r"\bvs\.?\b|\bversus\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    return ""


def _extract_multi_concepts(question: str) -> tuple[str, List[str]]:
    cleaned = " ".join((question or "").split())
    comparison_tail = _extract_comparison_tail(cleaned)
    if comparison_tail:
        concepts = _unique_in_order(_MULTI_CONCEPT_SPLIT_RE.split(comparison_tail))
        if len(concepts) >= 2:
            return "comparison", concepts

    definition_match = _DEFINITION_HEAD_PATTERN.match(cleaned)
    if definition_match:
        concepts = _unique_in_order(_MULTI_CONCEPT_SPLIT_RE.split(definition_match.group(1)))
        if len(concepts) >= 2:
            return "definition_multi", concepts

    return "single", []


def _definition_query_for_concept(concept: str) -> str:
    if concept == "SQL":
        return "definition of SQL database language"
    if concept == "NoSQL":
        return "definition of NoSQL database"
    return f"definition of {concept}"


def _comparison_query_for_concepts(concepts: Sequence[str]) -> str:
    if len(concepts) == 2:
        return f"difference between {concepts[0]} and {concepts[1]} databases"
    return f"comparison between {' and '.join(concepts)}"


def _build_query_intent(cleaned: str, intent_type: str, concepts: Sequence[str]) -> QueryIntent:
    normalized_concepts = _unique_in_order(concepts)
    if intent_type == "single" or not normalized_concepts:
        return {
            "mode": "single",
            "intent_type": "single",
            "required_concepts": [],
            "subqueries": [],
            "search_queries": [
                {
                    "label": "original question",
                    "query": cleaned,
                    "concept": None,
                    "query_kind": "original",
                }
            ],
        }

    if intent_type == "comparison":
        comparison_query = _comparison_query_for_concepts(normalized_concepts)
        subqueries: List[QuerySearchSpec] = [
            {
                "label": concept,
                "query": _definition_query_for_concept(concept),
                "concept": concept,
                "query_kind": "concept_support",
            }
            for concept in normalized_concepts
        ]
        search_queries: List[QuerySearchSpec] = [
            {
                "label": "comparison",
                "query": comparison_query,
                "concept": None,
                "query_kind": "comparison",
            }
        ]
        if len(normalized_concepts) == 2:
            search_queries.append(
                {
                    "label": "vs comparison",
                    "query": f"{normalized_concepts[0]} vs {normalized_concepts[1]} comparison",
                    "concept": None,
                    "query_kind": "comparison",
                }
            )
        search_queries.extend(subqueries)
        return {
            "mode": "multi",
            "intent_type": "comparison",
            "required_concepts": normalized_concepts,
            "subqueries": subqueries,
            "search_queries": search_queries,
        }

    subqueries = [
        {
            "label": concept,
            "query": _definition_query_for_concept(concept),
            "concept": concept,
            "query_kind": "concept_definition",
        }
        for concept in normalized_concepts
    ]
    search_queries = list(subqueries)
    search_queries.append(
        {
            "label": "combined definition",
            "query": f"what is {' and '.join(normalized_concepts)}",
            "concept": None,
            "query_kind": "combined_definition",
        }
    )
    return {
        "mode": "multi",
        "intent_type": "definition_multi",
        "required_concepts": normalized_concepts,
        "subqueries": subqueries,
        "search_queries": search_queries,
    }


def analyze_query_intent(
    question: str,
    *,
    fallback_required_concepts: Sequence[str] = (),
    fallback_intent_type: str | None = None,
) -> QueryIntent:
    cleaned = " ".join((question or "").split()).strip()
    intent_type, concepts = _extract_multi_concepts(cleaned)
    if intent_type != "single":
        return _build_query_intent(cleaned, intent_type, concepts)

    fallback_concepts = _unique_in_order(fallback_required_concepts)
    if fallback_concepts and fallback_intent_type in {"definition_multi", "comparison"}:
        return _build_query_intent(cleaned, fallback_intent_type, fallback_concepts)

    return _build_query_intent(cleaned, "single", [])


def _reciprocal_rank_fusion(results_list: List[List[Dict[str, Any]]], k: int = RRF_K) -> List[Dict[str, Any]]:
    rrf_scores: Dict[str, Dict[str, Any]] = {}

    for results in results_list:
        for rank, raw_doc in enumerate(results, start=1):
            doc = _normalize_doc(raw_doc)
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            score = 1.0 / (k + rank)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {"doc": doc, "rrf_score": 0.0}
            rrf_scores[chunk_id]["rrf_score"] += score

    sorted_docs = sorted(rrf_scores.values(), key=lambda item: item["rrf_score"], reverse=True)
    return [{**item["doc"], "rrf_score": round(item["rrf_score"], 4)} for item in sorted_docs]


async def _retrieve_vector_context(
    question: str,
    selected_file_ids: Sequence[str],
    *,
    k: int = RETRIEVAL_K,
    log_prefix: str = "vector retrieval",
) -> tuple[List[Dict[str, Any]], str]:
    return await retrieve_vector_context(
        question,
        selected_file_ids,
        k=k,
        log_prefix=log_prefix,
    )


async def _run_hybrid_search_for_query(
    query_spec: QuerySearchSpec,
    selected_file_ids: Sequence[str],
    emit: EventCallback,
    *,
    retrieval_k: int,
    log_prefix: str,
) -> Dict[str, Any]:
    query_text = query_spec["query"]
    label = query_spec["label"]
    scoped_log_prefix = f"{log_prefix}:{label}"
    vector_failed = False
    vector_retrieval_degraded = False
    fulltext_failed = False
    retrieval_mode = "primary"

    await _safe_emit(
        emit,
        f"[retrieval] retrieving candidate chunks for query: {query_text}",
        query_text,
        "retrieval",
    )

    async def run_vector_search() -> List[Dict[str, Any]]:
        nonlocal vector_failed, vector_retrieval_degraded, retrieval_mode

        try:
            rows, retrieval_mode = await _retrieve_vector_context(
                query_text,
                selected_file_ids,
                k=retrieval_k,
                log_prefix=scoped_log_prefix,
            )
            await _safe_emit(
                emit,
                f"[retrieval] vector search completed with {len(rows)} hits ({retrieval_mode}) for {label}.",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] vector_search label=%r query=%r hits=%s mode=%s top_chunk_ids=%s",
                log_prefix,
                label,
                query_text[:160],
                len(rows),
                retrieval_mode,
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [_normalize_doc(row) for row in rows]
        except Exception as err:
            vector_failed = True
            vector_retrieval_degraded = is_retryable_embedding_error(err)
            logger.warning("[%s] vector retrieval failed for %r: %s", log_prefix, label, err)
            await _safe_emit(
                emit,
                f"[retrieval] vector search failed for {label}: {err}",
                0,
                "retrieval",
            )
            return []

    async def run_fulltext_search() -> List[Dict[str, Any]]:
        nonlocal fulltext_failed

        try:
            rows = await asyncio.to_thread(
                pg_service.retrieve_context_by_keywords,
                query_text,
                selected_file_ids,
                retrieval_k,
            )
            await _safe_emit(
                emit,
                f"[retrieval] fulltext search completed with {len(rows)} hits for {label}.",
                len(rows),
                "retrieval",
            )
            logger.info(
                "[%s] fulltext_search label=%r query=%r hits=%s top_chunk_ids=%s",
                log_prefix,
                label,
                query_text[:160],
                len(rows),
                [row.get("chunkId") or row.get("chunkid") for row in rows[:5]],
            )
            return [_normalize_doc(row) for row in rows]
        except Exception as err:
            fulltext_failed = True
            logger.warning("[%s] fulltext retrieval failed for %r: %s", log_prefix, label, err)
            await _safe_emit(
                emit,
                f"[retrieval] fulltext search failed for {label}: {err}",
                0,
                "retrieval",
            )
            return []

    vector_results, fulltext_results = await asyncio.gather(
        run_vector_search(),
        run_fulltext_search(),
    )
    fused = _reciprocal_rank_fusion([vector_results, fulltext_results], k=RRF_K)
    logger.info(
        "[%s] subquery_summary label=%r query=%r kind=%s vector_hits=%s fulltext_hits=%s fused_top_chunk_ids=%s",
        log_prefix,
        label,
        query_text[:160],
        query_spec.get("query_kind"),
        len(vector_results),
        len(fulltext_results),
        [doc.get("chunkId") for doc in fused[:5]],
    )
    return {
        "query_spec": query_spec,
        "vector_results": vector_results,
        "fulltext_results": fulltext_results,
        "fused": fused,
        "vector_failed": vector_failed,
        "fulltext_failed": fulltext_failed,
        "vector_retrieval_degraded": vector_retrieval_degraded,
        "retrieval_mode": retrieval_mode,
    }


def _merge_candidate_documents(
    search_results: Sequence[Dict[str, Any]],
    *,
    max_docs_to_grade: int,
) -> List[Dict[str, Any]]:
    global_inputs: List[List[Dict[str, Any]]] = []
    retrieved_for_concepts: Dict[str, List[str]] = {}
    query_matches: Dict[str, List[str]] = {}
    doc_index: Dict[str, Dict[str, Any]] = {}
    reserved_chunk_ids: List[str] = []
    seen_reserved: set[str] = set()

    for result in search_results:
        query_spec = result["query_spec"]
        concept = query_spec.get("concept")
        query_text = query_spec["query"]
        fused = result.get("fused", [])
        global_inputs.extend([result.get("vector_results", []), result.get("fulltext_results", [])])

        for doc in fused:
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            if concept:
                retrieved_for_concepts.setdefault(chunk_id, [])
                retrieved_for_concepts[chunk_id] = _unique_in_order(retrieved_for_concepts[chunk_id] + [concept])
            query_matches.setdefault(chunk_id, [])
            query_matches[chunk_id] = _unique_in_order(query_matches[chunk_id] + [query_text])

            existing = doc_index.get(chunk_id)
            if existing is None or doc.get("rrf_score", 0.0) >= existing.get("rrf_score", 0.0):
                doc_index[chunk_id] = _normalize_doc(doc)

        if concept:
            for doc in fused[:RESERVED_CANDIDATES_PER_SUBQUERY]:
                chunk_id = doc.get("chunkId")
                if not chunk_id or chunk_id in seen_reserved:
                    continue
                seen_reserved.add(chunk_id)
                reserved_chunk_ids.append(chunk_id)

    global_fused = _reciprocal_rank_fusion(global_inputs, k=RRF_K) if global_inputs else []
    for doc in global_fused:
        chunk_id = doc.get("chunkId")
        if not chunk_id:
            continue
        existing = doc_index.get(chunk_id)
        if existing is None or doc.get("rrf_score", 0.0) >= existing.get("rrf_score", 0.0):
            doc_index[chunk_id] = _normalize_doc(doc)

    ordered_chunk_ids = list(reserved_chunk_ids)
    for doc in global_fused:
        chunk_id = doc.get("chunkId")
        if chunk_id and chunk_id not in ordered_chunk_ids:
            ordered_chunk_ids.append(chunk_id)

    candidate_documents: List[Dict[str, Any]] = []
    for chunk_id in ordered_chunk_ids[:max_docs_to_grade]:
        base_doc = dict(doc_index[chunk_id])
        base_doc["retrieved_for_concepts"] = retrieved_for_concepts.get(chunk_id, [])
        base_doc["matched_queries"] = query_matches.get(chunk_id, [])
        candidate_documents.append(base_doc)

    return candidate_documents


async def retrieve_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    retrieval_k: int = RETRIEVAL_K,
    max_docs_to_grade: int = MAX_DOCS_TO_GRADE,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    current_query = state["current_query"]
    selected_file_ids = state["selected_file_ids"]
    previous_intent = state.get("query_intent", {})
    query_intent = analyze_query_intent(
        current_query,
        fallback_required_concepts=previous_intent.get("required_concepts", []),
        fallback_intent_type=previous_intent.get("intent_type"),
    )
    state["query_intent"] = query_intent
    logger.info(
        "[%s] retrieve_documents start query=%r rewrite_count=%s selected_files=%s mode=%s intent_type=%s required_concepts=%s",
        log_prefix,
        current_query[:160],
        state.get("rewrite_count", 0),
        len(selected_file_ids),
        query_intent["mode"],
        query_intent["intent_type"],
        query_intent["required_concepts"],
    )

    search_results = []
    for query_spec in query_intent["search_queries"]:
        search_results.append(
            await _run_hybrid_search_for_query(
                query_spec,
                selected_file_ids,
                emit,
                retrieval_k=retrieval_k,
                log_prefix=log_prefix,
            )
        )

    candidate_documents = _merge_candidate_documents(
        search_results,
        max_docs_to_grade=max_docs_to_grade,
    )

    vector_hits = sum(len(result["vector_results"]) for result in search_results)
    fulltext_hits = sum(len(result["fulltext_results"]) for result in search_results)
    vector_failed = any(result["vector_failed"] for result in search_results)
    fulltext_failed = any(result["fulltext_failed"] for result in search_results)
    vector_retrieval_degraded = any(result["vector_retrieval_degraded"] for result in search_results)
    state["candidate_documents"] = candidate_documents
    state["covered_concepts"] = []
    state["missing_concepts"] = list(query_intent["required_concepts"])
    state["vector_retrieval_degraded"] = vector_retrieval_degraded
    state["retrieval_mode_summary"] = {
        "vector_hits": vector_hits,
        "fulltext_hits": fulltext_hits,
        "vector_failed": vector_failed,
        "fulltext_failed": fulltext_failed,
        "vector_retrieval_degraded": vector_retrieval_degraded,
        "subquery_summaries": [
            {
                "label": result["query_spec"]["label"],
                "query": result["query_spec"]["query"],
                "concept": result["query_spec"].get("concept"),
                "query_kind": result["query_spec"].get("query_kind"),
                "vector_hits": len(result["vector_results"]),
                "fulltext_hits": len(result["fulltext_results"]),
                "retrieval_mode": result["retrieval_mode"],
                "top_chunk_ids": [doc.get("chunkId") for doc in result["fused"][:5]],
            }
            for result in search_results
        ],
    }
    logger.info(
        "[%s] retrieval merged_candidates=%s top_sources=%s",
        log_prefix,
        len(candidate_documents),
        [
            {
                "chunk_id": doc.get("chunkId"),
                "source": doc.get("source"),
                "score": doc.get("rrf_score"),
                "retrieved_for_concepts": doc.get("retrieved_for_concepts", []),
            }
            for doc in candidate_documents[:5]
        ],
    )

    await _safe_emit(
        emit,
        f"[retrieval] merged results produced {len(candidate_documents)} candidate chunks.",
        len(candidate_documents),
        "retrieval",
    )
    return state


async def grade_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    question = state["question"]
    candidate_documents = state.get("candidate_documents", [])
    query_intent = state.get("query_intent") or analyze_query_intent(question)
    required_concepts = query_intent.get("required_concepts", [])
    intent_type = query_intent.get("intent_type", "single")
    filtered_documents: List[Dict[str, Any]] = []
    logger.info(
        "[%s] grade_documents start question=%r candidate_chunks=%s required_concepts=%s intent_type=%s",
        log_prefix,
        question[:160],
        len(candidate_documents),
        required_concepts,
        intent_type,
    )

    await _safe_emit(
        emit,
        f"[grader] grading {len(candidate_documents)} retrieved chunks for relevance.",
        len(candidate_documents),
        "grader",
    )

    if required_concepts:
        schema = {
            "type": "object",
            "properties": {
                "relevant": {"type": "string", "enum": ["yes", "no"]},
                "covered_concepts": {
                    "type": "array",
                    "items": {"type": "string", "enum": required_concepts},
                },
                "reason": {"type": "string"},
            },
            "required": ["relevant", "covered_concepts", "reason"],
        }
    else:
        schema = {
            "type": "object",
            "properties": {
                "relevant": {"type": "string", "enum": ["yes", "no"]},
                "reason": {"type": "string"},
            },
            "required": ["relevant", "reason"],
        }

    semaphore = asyncio.Semaphore(DOCUMENT_GRADING_CONCURRENCY) if DOCUMENT_GRADING_CONCURRENCY else None

    async def grade_one(index: int, doc: Dict[str, Any]) -> tuple[int, bool, Dict[str, Any], List[str]]:
        retrieved_for = _unique_in_order(doc.get("retrieved_for_concepts", []))
        if required_concepts:
            concept_lines = "\n".join(f"- {concept}" for concept in required_concepts)
            prompt = f"""
You are filtering retrieval chunks for a multi-concept RAG system.
Intent type: {intent_type}
- Mark relevant=yes only if this chunk directly supports at least one required concept or directly helps compare the required concepts.
- Do not treat incidental mentions as evidence.
- Return only the concepts that are directly supported by this chunk itself.

User question:
{question}

Required concepts:
{concept_lines}

Chunk surfaced for concepts (retrieval hint only, not evidence):
{retrieved_for}

Document:
Source: {doc.get("source")}
Page: {doc.get("page")}
Content:
{(doc.get("text") or "")[:MAX_DOC_PREVIEW_CHARS]}
"""
        else:
            prompt = f"""
You are filtering retrieval chunks for a RAG system.
Mark a document as relevant only if it contains information that helps answer the question directly.

Question:
{question}

Document:
Source: {doc.get("source")}
Page: {doc.get("page")}
Content:
{(doc.get("text") or "")[:MAX_DOC_PREVIEW_CHARS]}
"""
        try:
            if semaphore is None:
                result = await generate_structured_json(
                    prompt,
                    schema,
                    operation_name="Adaptive RAG grade document",
                    temperature=0.0,
                )
            else:
                async with semaphore:
                    result = await generate_structured_json(
                        prompt,
                        schema,
                        operation_name="Adaptive RAG grade document",
                        temperature=0.0,
                    )

            covered = _unique_in_order(result.get("covered_concepts", []))
            should_keep = result.get("relevant") == "yes"
            logger.info(
                "[%s] grade_document chunk_id=%s relevant=%s retrieved_for=%s covered=%s source=%r reason=%r",
                log_prefix,
                doc.get("chunkId"),
                result.get("relevant"),
                retrieved_for,
                covered,
                doc.get("source"),
                (result.get("reason") or "")[:200],
            )
            merged_doc = {**doc, "covered_concepts": covered}
            return index, should_keep, merged_doc, covered
        except Exception as err:
            logger.warning("[%s] document grading failed; keeping chunk %s: %s", log_prefix, doc.get("chunkId"), err)
            merged_doc = {**doc, "covered_concepts": []}
            return index, True, merged_doc, []

    grading_results = await asyncio.gather(
        *(grade_one(index, doc) for index, doc in enumerate(candidate_documents))
    )
    grading_results.sort(key=lambda item: item[0])

    covered_concepts: List[str] = []
    for _, should_keep, doc, doc_covered_concepts in grading_results:
        if should_keep:
            filtered_documents.append(doc)
            covered_concepts = _unique_in_order(covered_concepts + doc_covered_concepts)

    missing_concepts = [concept for concept in required_concepts if concept not in covered_concepts]
    state["filtered_documents"] = filtered_documents
    state["covered_concepts"] = covered_concepts
    state["missing_concepts"] = missing_concepts
    logger.info(
        "[%s] grade_documents kept_chunks=%s kept_chunk_ids=%s covered_concepts=%s missing_concepts=%s",
        log_prefix,
        len(filtered_documents),
        [doc.get("chunkId") for doc in filtered_documents],
        covered_concepts,
        missing_concepts,
    )
    await _safe_emit(
        emit,
        f"[grader] kept {len(filtered_documents)} relevant chunks.",
        len(filtered_documents),
        "grader",
    )
    return state


async def rewrite_query_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    max_rewrite_attempts: int = MAX_REWRITE_ATTEMPTS,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalState:
    rewrite_count = state.get("rewrite_count", 0) + 1
    state["rewrite_count"] = rewrite_count
    query_intent = state.get("query_intent") or analyze_query_intent(state.get("original_question", ""))
    logger.info(
        "[%s] rewrite_query start attempt=%s original_question=%r current_query=%r intent_type=%s required_concepts=%s",
        log_prefix,
        rewrite_count,
        state.get("original_question", "")[:160],
        state.get("current_query", "")[:160],
        query_intent.get("intent_type"),
        query_intent.get("required_concepts", []),
    )

    await _safe_emit(
        emit,
        f"[rewrite] rewriting query (attempt {rewrite_count}/{max_rewrite_attempts}).",
        rewrite_count,
        "rewrite",
    )

    schema = {
        "type": "object",
        "properties": {
            "rewritten_query": {"type": "string"},
        },
        "required": ["rewritten_query"],
    }
    prompt = f"""
Rewrite the user question into a concise retrieval query for searching within course documents.
- Keep the original intent and all required concepts.
- Preserve the question style: if it is a comparison, keep it as a comparison; if it is asking for definitions, keep it as a definition query.
- Prefer domain keywords, entity names, and technical terms.
- Do not answer the question.
- Return one short query.

Original question:
{state["original_question"]}

Detected intent type:
{query_intent.get("intent_type", "single")}

Required concepts:
{query_intent.get("required_concepts", [])}
"""

    try:
        result = await generate_structured_json(
            prompt,
            schema,
            operation_name="Adaptive RAG rewrite query",
            temperature=0.0,
        )
        rewritten_query = (result.get("rewritten_query") or "").strip()
    except Exception as err:
        logger.warning("[%s] query rewrite failed; using original question: %s", log_prefix, err)
        rewritten_query = ""

    state["current_query"] = rewritten_query or state["original_question"]
    state["query_intent"] = analyze_query_intent(
        state["current_query"],
        fallback_required_concepts=query_intent.get("required_concepts", []),
        fallback_intent_type=query_intent.get("intent_type"),
    )
    logger.info(
        "[%s] rewrite_query completed attempt=%s rewritten_query=%r preserved_intent_type=%s preserved_required_concepts=%s",
        log_prefix,
        rewrite_count,
        state["current_query"][:160],
        state["query_intent"].get("intent_type"),
        state["query_intent"].get("required_concepts", []),
    )
    await _safe_emit(
        emit,
        f"[rewrite] rewritten query: {state['current_query']}",
        state["current_query"],
        "rewrite",
    )
    return state


async def run_adaptive_retrieval(
    question: str,
    selected_file_ids: List[str],
    *,
    emit: EventCallback | None = None,
    retrieval_k: int = RETRIEVAL_K,
    max_docs_to_grade: int = MAX_DOCS_TO_GRADE,
    max_rewrite_attempts: int = MAX_REWRITE_ATTEMPTS,
    log_prefix: str = "AdaptiveRetrieval",
) -> AdaptiveRetrievalResult:
    async def noop_emit(message: str, data: Any = None, event_type: str = "retrieval") -> None:
        return None

    emit_callback = emit or noop_emit
    logger.info(
        "[%s] run_start question=%r selected_files=%s retrieval_k=%s max_docs_to_grade=%s",
        log_prefix,
        question[:160],
        len(selected_file_ids),
        retrieval_k,
        max_docs_to_grade,
    )

    initial_intent = analyze_query_intent(question.strip())

    if not selected_file_ids:
        logger.warning("[%s] run_end empty_selection", log_prefix)
        return {
            "documents": [],
            "candidate_documents": [],
            "rewrite_count": 0,
            "current_query": question.strip(),
            "fallback_reason": EMPTY_SELECTION_FALLBACK_REASON,
            "retrieval_mode_summary": {
                "vector_hits": 0,
                "fulltext_hits": 0,
                "vector_failed": False,
                "fulltext_failed": False,
                "vector_retrieval_degraded": False,
                "subquery_summaries": [],
            },
            "vector_retrieval_degraded": False,
            "query_intent": initial_intent,
            "covered_concepts": [],
            "missing_concepts": initial_intent["required_concepts"],
        }

    state: AdaptiveRetrievalState = {
        "question": question.strip(),
        "original_question": question.strip(),
        "selected_file_ids": list(selected_file_ids),
        "current_query": question.strip(),
        "rewrite_count": 0,
        "candidate_documents": [],
        "filtered_documents": [],
        "fallback_reason": None,
        "query_intent": initial_intent,
        "covered_concepts": [],
        "missing_concepts": [],
        "retrieval_mode_summary": {
            "vector_hits": 0,
            "fulltext_hits": 0,
            "vector_failed": False,
            "fulltext_failed": False,
            "vector_retrieval_degraded": False,
            "subquery_summaries": [],
        },
        "vector_retrieval_degraded": False,
    }

    while True:
        state = await retrieve_documents_node(
            state,
            emit_callback,
            retrieval_k=retrieval_k,
            max_docs_to_grade=max_docs_to_grade,
            log_prefix=log_prefix,
        )
        state = await grade_documents_node(
            state,
            emit_callback,
            log_prefix=log_prefix,
        )

        if state.get("filtered_documents"):
            logger.info(
                "[%s] run_end success kept_chunks=%s rewrite_count=%s covered_concepts=%s missing_concepts=%s",
                log_prefix,
                len(state.get("filtered_documents", [])),
                state.get("rewrite_count", 0),
                state.get("covered_concepts", []),
                state.get("missing_concepts", []),
            )
            return {
                "documents": state.get("filtered_documents", []),
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": None,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
                "query_intent": state.get("query_intent", initial_intent),
                "covered_concepts": state.get("covered_concepts", []),
                "missing_concepts": state.get("missing_concepts", []),
            }

        if state.get("rewrite_count", 0) >= max_rewrite_attempts:
            logger.warning(
                "[%s] run_end no_documents rewrite_count=%s fallback_reason=%s missing_concepts=%s",
                log_prefix,
                state.get("rewrite_count", 0),
                NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
                state.get("missing_concepts", []),
            )
            return {
                "documents": [],
                "candidate_documents": state.get("candidate_documents", []),
                "rewrite_count": state.get("rewrite_count", 0),
                "current_query": state.get("current_query", question.strip()),
                "fallback_reason": NO_RELEVANT_DOCUMENTS_FALLBACK_REASON,
                "retrieval_mode_summary": state.get("retrieval_mode_summary", {}),
                "vector_retrieval_degraded": state.get("vector_retrieval_degraded", False),
                "query_intent": state.get("query_intent", initial_intent),
                "covered_concepts": state.get("covered_concepts", []),
                "missing_concepts": state.get("missing_concepts", []),
            }

        state = await rewrite_query_node(
            state,
            emit_callback,
            max_rewrite_attempts=max_rewrite_attempts,
            log_prefix=log_prefix,
        )
