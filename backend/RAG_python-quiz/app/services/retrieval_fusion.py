from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from app.services.rag_shared import normalize_concepts
from app.services.retrieval_intent import _clean_concept_fragment

NormalizeDoc = Callable[[Dict[str, Any]], Dict[str, Any]]
RankFusion = Callable[..., List[Dict[str, Any]]]


def reciprocal_rank_fusion(
    results_list: List[List[Dict[str, Any]]],
    *,
    normalize_doc: NormalizeDoc,
    k: int,
) -> List[Dict[str, Any]]:
    rrf_scores: Dict[str, Dict[str, Any]] = {}

    for results in results_list:
        for rank, raw_doc in enumerate(results, start=1):
            doc = normalize_doc(raw_doc)
            chunk_id = doc.get("chunkId")
            if not chunk_id:
                continue

            score = 1.0 / (k + rank)
            if chunk_id not in rrf_scores:
                rrf_scores[chunk_id] = {"doc": doc, "rrf_score": 0.0}
            rrf_scores[chunk_id]["rrf_score"] += score

    sorted_docs = sorted(rrf_scores.values(), key=lambda item: item["rrf_score"], reverse=True)
    return [{**item["doc"], "rrf_score": round(item["rrf_score"], 4)} for item in sorted_docs]


def merge_candidate_documents(
    search_results: Sequence[Dict[str, Any]],
    *,
    max_docs_to_grade: int,
    normalize_doc: NormalizeDoc,
    reciprocal_rank_fusion_func: RankFusion,
    rrf_k: int,
    reserved_candidates_per_subquery: int,
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
                retrieved_for_concepts[chunk_id] = normalize_concepts(
                    retrieved_for_concepts[chunk_id] + [concept],
                    normalizer=_clean_concept_fragment,
                )
            query_matches.setdefault(chunk_id, [])
            query_matches[chunk_id] = normalize_concepts(
                query_matches[chunk_id] + [query_text],
                normalizer=_clean_concept_fragment,
            )

            existing = doc_index.get(chunk_id)
            if existing is None or doc.get("rrf_score", 0.0) >= existing.get("rrf_score", 0.0):
                doc_index[chunk_id] = normalize_doc(doc)

        if concept:
            for doc in fused[:reserved_candidates_per_subquery]:
                chunk_id = doc.get("chunkId")
                if not chunk_id or chunk_id in seen_reserved:
                    continue
                seen_reserved.add(chunk_id)
                reserved_chunk_ids.append(chunk_id)

    global_fused = reciprocal_rank_fusion_func(global_inputs, k=rrf_k) if global_inputs else []
    for doc in global_fused:
        chunk_id = doc.get("chunkId")
        if not chunk_id:
            continue
        existing = doc_index.get(chunk_id)
        if existing is None or doc.get("rrf_score", 0.0) >= existing.get("rrf_score", 0.0):
            doc_index[chunk_id] = normalize_doc(doc)

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
