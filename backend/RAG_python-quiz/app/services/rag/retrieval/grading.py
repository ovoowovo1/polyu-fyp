from __future__ import annotations

import asyncio
import math
import hashlib
import json
from typing import Any, Dict, List, Sequence

from app.logger import get_logger
from app.services.rag.retrieval import intent as retrieval_intent
from app.services.rag.retrieval.types import AdaptiveRetrievalState, EventCallback
from app.services.rag.shared.helpers import normalize_concepts, safe_emit
from app.services.rag.retrieval.intent import _clean_concept_fragment
from app.services.rag.citation.service import image_inputs

logger = get_logger(__name__)

DOCUMENT_RELEVANCE_THRESHOLD = 0.5
MAX_GRADING_BATCH_SIZE = 8
DOCUMENT_GRADING_CONCURRENCY = 2


def build_document_grading_schema(required_concepts: Sequence[str]) -> Dict[str, Any]:
    covered_concepts_schema: Dict[str, Any] = {"type": "string"}
    if required_concepts:
        covered_concepts_schema = {"type": "string", "enum": list(required_concepts)}

    return {
        "type": "object",
        "properties": {
            "grades": {
                "type": "array",
                "maxItems": MAX_GRADING_BATCH_SIZE,
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string", "minLength": 1},
                        "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                        "covered_concepts": {
                            "type": "array",
                            "items": covered_concepts_schema,
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["chunk_id", "relevance_score", "covered_concepts", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["grades"],
        "additionalProperties": False,
    }


def build_document_grading_prompt(
    *,
    question: str,
    documents: Sequence[Dict[str, Any]],
    required_concepts: Sequence[str],
    intent_type: str,
) -> str:
    concept_lines = "\n".join(f"- {concept}" for concept in required_concepts) or "(none)"
    document_lines = []
    for index, doc in enumerate(documents, start=1):
        retrieved_for = normalize_concepts(
            doc.get("retrieved_for_concepts", []),
            normalizer=_clean_concept_fragment,
        )
        document_lines.append(
            f"""[Chunk {doc.get('chunkId') or f'candidate-{index}'}]
Source: {doc.get('source')}
Page: {doc.get('page')}
Retrieved for concepts (hint only, not evidence): {retrieved_for}
Content:
{doc.get('text') or ''}"""
        )

    return f"""
You are grading a batch of retrieval chunks for a course-document RAG system.
Return exactly one grade for every supplied chunk and no other chunk IDs.

Use relevance_score from 0.0 to 1.0:
- 0.0 means irrelevant or only incidental mention.
- 0.5 means the chunk directly supports the question at a usable level.
- 1.0 means the chunk is highly direct and sufficient evidence.
- Score the chunk content itself, not the retrieval hint.
- covered_concepts must contain only concepts directly supported by that chunk.
- If there are no required concepts, return covered_concepts as an empty array.
- Do not answer the user question.

Question:
{question}

Intent type:
{intent_type}

Required concepts:
{concept_lines}

Candidate chunks:
{chr(10).join(document_lines)}
"""


async def run_document_grader(
    prompt: str,
    schema: Dict[str, Any],
    semaphore: asyncio.Semaphore | None = None,
    *,
    generate_structured_json_func,
    images: list | None = None,
) -> Dict[str, Any]:
    async def generate() -> Dict[str, Any]:
        return await generate_structured_json_func(
            prompt,
            schema,
            operation_name="Adaptive RAG grade document batch",
            temperature=0.0,
            image_inputs=images or [],
        )

    if semaphore is None:
        return await generate()
    async with semaphore:
        return await generate()


def _normalize_covered_concepts(raw_concepts: Any, required_concepts: Sequence[str]) -> List[str]:
    if not isinstance(raw_concepts, list) or not all(isinstance(value, str) for value in raw_concepts):
        raise ValueError("covered_concepts must be a string array")

    required_by_key = {concept.casefold(): concept for concept in required_concepts}
    normalized: List[str] = []
    for raw_concept in raw_concepts:
        cleaned = _clean_concept_fragment(raw_concept)
        if not cleaned:
            continue
        if cleaned.casefold() not in required_by_key:
            raise ValueError(f"unknown covered concept: {cleaned!r}")
        normalized.append(required_by_key[cleaned.casefold()])
    return normalize_concepts(normalized, normalizer=_clean_concept_fragment)


def _normalize_batch_grades(
    result: Any,
    candidate_documents: Sequence[Dict[str, Any]],
    required_concepts: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("grades"), list):
        raise ValueError("grading result must contain a grades array")

    candidate_ids = [doc.get("chunkId") for doc in candidate_documents]
    if any(not isinstance(chunk_id, str) or not chunk_id for chunk_id in candidate_ids):
        raise ValueError("every candidate must have a chunkId")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate chunk IDs must be unique")
    if len(result["grades"]) != len(candidate_ids):
        raise ValueError("grading result must contain exactly one grade per candidate")

    candidate_id_set = set(candidate_ids)
    normalized: Dict[str, Dict[str, Any]] = {}
    for grade in result["grades"]:
        if not isinstance(grade, dict):
            raise ValueError("each grade must be an object")
        chunk_id = grade.get("chunk_id")
        score = grade.get("relevance_score")
        reason = grade.get("reason")
        if not isinstance(chunk_id, str) or chunk_id not in candidate_id_set:
            raise ValueError(f"unknown grading chunk ID: {chunk_id!r}")
        if chunk_id in normalized:
            raise ValueError(f"duplicate grading chunk ID: {chunk_id!r}")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"invalid relevance score for {chunk_id!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"grading reason must be non-empty for {chunk_id!r}")
        normalized[chunk_id] = {
            "relevance_score": float(score),
            "covered_concepts": _normalize_covered_concepts(
                grade.get("covered_concepts"),
                required_concepts,
            ),
            "grading_reason": reason.strip(),
        }

    return normalized


def collect_grading_outputs(
    grading_results: Sequence[tuple[Dict[str, Any], float, List[str], str]],
    required_concepts: Sequence[str],
    *,
    existing_documents: Sequence[Dict[str, Any]] = (),
    existing_covered_concepts: Sequence[str] = (),
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    filtered_documents = list(existing_documents)
    covered_concepts = normalize_concepts(
        list(existing_covered_concepts),
        normalizer=_clean_concept_fragment,
    )
    existing_ids = {doc.get("chunkId") for doc in filtered_documents}

    for doc, relevance_score, doc_covered_concepts, grading_reason in grading_results:
        if relevance_score < DOCUMENT_RELEVANCE_THRESHOLD or doc.get("chunkId") in existing_ids:
            continue
        filtered_documents.append(
            {
                **doc,
                "relevance_score": relevance_score,
                "covered_concepts": doc_covered_concepts,
                "grading_reason": grading_reason,
            }
        )
        existing_ids.add(doc.get("chunkId"))
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
    candidate_documents = list(state.get("candidate_documents", []))
    existing_documents = list(state.get("filtered_documents", []))
    query_intent = state.get("query_intent")
    if not query_intent:
        query_intent = await retrieval_intent.classify_query_intent(
            question,
            generate_structured_json_func=generate_structured_json_func,
        )

    required_concepts = normalize_concepts(
        query_intent.get("required_concepts", []),
        normalizer=_clean_concept_fragment,
    )
    intent_type = query_intent.get("intent_type", "single")
    existing_covered = normalize_concepts(
        state.get("covered_concepts", []),
        normalizer=_clean_concept_fragment,
    )
    state["query_intent"] = query_intent

    logger.info(
        "[%s] grade_documents batch_start question=%r candidate_chunks=%s required_concepts=%s intent_type=%s",
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

    if not candidate_documents:
        state["filtered_documents"] = existing_documents
        state["covered_concepts"] = existing_covered
        state["missing_concepts"] = [concept for concept in required_concepts if concept not in existing_covered]
        state["grading_failed"] = state.get("grading_failed", False)
        return state

    semaphore = asyncio.Semaphore(DOCUMENT_GRADING_CONCURRENCY)

    async def grade_batch(batch):
        schema = build_document_grading_schema(required_concepts)
        schema["properties"]["grades"]["items"]["properties"]["chunk_id"]["enum"] = [d["chunkId"] for d in batch]
        prompt = build_document_grading_prompt(question=question, documents=batch,
            required_concepts=required_concepts, intent_type=intent_type)
        result = await run_document_grader(prompt, schema, semaphore,
            generate_structured_json_func=generate_structured_json_func, images=image_inputs(batch)[:6])
        return _normalize_batch_grades(result, batch, required_concepts)

    memo = state.setdefault("grading_cache", {})
    def cache_key(doc):
        prompt = build_document_grading_prompt(question=question, documents=[doc],
            required_concepts=required_concepts, intent_type=intent_type)
        payload = [prompt, doc.get("fileId"), image_inputs([doc])]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    keys = {doc["chunkId"]: cache_key(doc) for doc in candidate_documents}
    normalized_grades = {doc["chunkId"]: memo[keys[doc["chunkId"]]] for doc in candidate_documents
                         if keys[doc["chunkId"]] in memo}
    pending = [doc for doc in candidate_documents if doc["chunkId"] not in normalized_grades]
    batches = [pending[i:i + MAX_GRADING_BATCH_SIZE]
               for i in range(0, len(pending), MAX_GRADING_BATCH_SIZE)]
    results = await asyncio.gather(*(grade_batch(batch) for batch in batches), return_exceptions=True)
    failed = False
    for batch, result in zip(batches, results):
        if isinstance(result, BaseException):
            failed = True
            logger.warning("[%s] grading failed for chunks=%s: %s", log_prefix,
                           [d["chunkId"] for d in batch], result)
        else:
            normalized_grades.update(result)
            for chunk_id, grade in result.items():
                memo[keys[chunk_id]] = grade
    state["grading_diagnostics"] = [{"chunk_id": d["chunkId"],
        **normalized_grades.get(d["chunkId"], {"grading_reason": "grading service failed"})}
        for d in candidate_documents]
    candidate_documents = [d for d in candidate_documents if d["chunkId"] in normalized_grades]

    grading_results = [
        (
            doc,
            normalized_grades[doc["chunkId"]]["relevance_score"],
            normalized_grades[doc["chunkId"]]["covered_concepts"],
            normalized_grades[doc["chunkId"]]["grading_reason"],
        )
        for doc in candidate_documents
    ]
    filtered_documents, covered_concepts, missing_concepts = collect_grading_outputs(
        grading_results,
        required_concepts,
        existing_documents=existing_documents,
        existing_covered_concepts=existing_covered,
    )
    state["filtered_documents"] = filtered_documents
    state["covered_concepts"] = covered_concepts
    state["missing_concepts"] = missing_concepts
    state["grading_failed"] = failed
    logger.info(
        "[%s] grade_documents batch_complete kept_chunks=%s covered_concepts=%s missing_concepts=%s score_threshold=%s",
        log_prefix,
        len(filtered_documents),
        covered_concepts,
        missing_concepts,
        DOCUMENT_RELEVANCE_THRESHOLD,
    )
    await safe_emit(
        emit,
        f"[grader] kept {len(filtered_documents)} relevant chunks.",
        len(filtered_documents),
        "grader",
    )
    return state
