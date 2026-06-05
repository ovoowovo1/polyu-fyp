from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Sequence

from app.logger import get_logger
from app.services.rag import retrieval_intent
from app.services.rag.adaptive_types import AdaptiveRetrievalState, EventCallback
from app.services.rag.rag_shared import normalize_concepts, safe_emit
from app.services.rag.retrieval_intent import _clean_concept_fragment

logger = get_logger(__name__)

MAX_DOC_PREVIEW_CHARS = 1800
DOCUMENT_GRADING_CONCURRENCY: int | None = None


def build_document_grading_schema(required_concepts: Sequence[str]) -> Dict[str, Any]:
    if required_concepts:
        return {
            "type": "object",
            "properties": {
                "relevant": {"type": "string", "enum": ["yes", "no"]},
                "covered_concepts": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(required_concepts)},
                },
                "reason": {"type": "string"},
            },
            "required": ["relevant", "covered_concepts", "reason"],
        }
    return {
        "type": "object",
        "properties": {
            "relevant": {"type": "string", "enum": ["yes", "no"]},
            "reason": {"type": "string"},
        },
        "required": ["relevant", "reason"],
    }


def build_document_grading_prompt(
    *,
    question: str,
    doc: Dict[str, Any],
    retrieved_for: Sequence[str],
    required_concepts: Sequence[str],
    intent_type: str,
) -> str:
    if required_concepts:
        concept_lines = "\n".join(f"- {concept}" for concept in required_concepts)
        return f"""
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
    return f"""
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


async def run_document_grader(
    prompt: str,
    schema: Dict[str, Any],
    semaphore: asyncio.Semaphore | None,
    *,
    generate_structured_json_func,
) -> Dict[str, Any]:
    if semaphore is None:
        return await generate_structured_json_func(
            prompt,
            schema,
            operation_name="Adaptive RAG grade document",
            temperature=0.0,
        )
    async with semaphore:
        return await generate_structured_json_func(
            prompt,
            schema,
            operation_name="Adaptive RAG grade document",
            temperature=0.0,
        )


async def grade_one_document(
    index: int,
    doc: Dict[str, Any],
    *,
    question: str,
    required_concepts: Sequence[str],
    intent_type: str,
    schema: Dict[str, Any],
    semaphore: asyncio.Semaphore | None,
    log_prefix: str,
    generate_structured_json_func,
) -> tuple[int, bool, Dict[str, Any], List[str]]:
    retrieved_for = normalize_concepts(doc.get("retrieved_for_concepts", []), normalizer=_clean_concept_fragment)
    prompt = build_document_grading_prompt(
        question=question,
        doc=doc,
        retrieved_for=retrieved_for,
        required_concepts=required_concepts,
        intent_type=intent_type,
    )
    try:
        result = await run_document_grader(
            prompt,
            schema,
            semaphore,
            generate_structured_json_func=generate_structured_json_func,
        )
        covered = normalize_concepts(result.get("covered_concepts", []), normalizer=_clean_concept_fragment)
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
        return index, should_keep, {**doc, "covered_concepts": covered}, covered
    except Exception as err:
        fallback_covered = [concept for concept in retrieved_for if concept in required_concepts]
        logger.warning(
            "[%s] document grading failed; keeping chunk %s with fallback_covered_concepts=%s: %s",
            log_prefix,
            doc.get("chunkId"),
            fallback_covered,
            err,
        )
        return index, True, {**doc, "covered_concepts": fallback_covered}, fallback_covered


def collect_grading_outputs(
    grading_results: Sequence[tuple[int, bool, Dict[str, Any], List[str]]],
    required_concepts: Sequence[str],
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    filtered_documents: List[Dict[str, Any]] = []
    covered_concepts: List[str] = []
    for _, should_keep, doc, doc_covered_concepts in grading_results:
        if should_keep:
            filtered_documents.append(doc)
            covered_concepts = normalize_concepts(
                covered_concepts + doc_covered_concepts,
                normalizer=_clean_concept_fragment,
            )

    missing_concepts = [concept for concept in required_concepts if concept not in covered_concepts]
    return filtered_documents, covered_concepts, missing_concepts


async def grade_documents_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    log_prefix: str,
    generate_structured_json_func,
) -> AdaptiveRetrievalState:
    question = state["question"]
    candidate_documents = state.get("candidate_documents", [])
    query_intent = state.get("query_intent") or retrieval_intent.analyze_query_intent(question)
    required_concepts = normalize_concepts(query_intent.get("required_concepts", []), normalizer=_clean_concept_fragment)
    intent_type = query_intent.get("intent_type", "single")
    logger.info(
        "[%s] grade_documents start question=%r candidate_chunks=%s required_concepts=%s intent_type=%s",
        log_prefix,
        question[:160],
        len(candidate_documents),
        required_concepts,
        intent_type,
    )

    await safe_emit(
        emit,
        f"[grader] grading {len(candidate_documents)} retrieved chunks for relevance.",
        len(candidate_documents),
        "grader",
    )

    schema = build_document_grading_schema(required_concepts)
    semaphore = asyncio.Semaphore(DOCUMENT_GRADING_CONCURRENCY) if DOCUMENT_GRADING_CONCURRENCY else None

    grading_results = await asyncio.gather(
        *(
            grade_one_document(
                index,
                doc,
                question=question,
                required_concepts=required_concepts,
                intent_type=intent_type,
                schema=schema,
                semaphore=semaphore,
                log_prefix=log_prefix,
                generate_structured_json_func=generate_structured_json_func,
            )
            for index, doc in enumerate(candidate_documents)
        )
    )
    grading_results.sort(key=lambda item: item[0])

    filtered_documents, covered_concepts, missing_concepts = collect_grading_outputs(
        grading_results,
        required_concepts,
    )
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
    await safe_emit(
        emit,
        f"[grader] kept {len(filtered_documents)} relevant chunks.",
        len(filtered_documents),
        "grader",
    )
    return state
