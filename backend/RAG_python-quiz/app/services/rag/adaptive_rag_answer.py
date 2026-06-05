from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

GenerateCitationEvidence = Callable[..., Awaitable[Dict[str, Any]]]


async def generate_answer_node(
    state: Dict[str, Any],
    emit,
    *,
    generate_citation_evidence: GenerateCitationEvidence,
    safe_emit,
    partial_coverage_reason: str,
    logger,
) -> Dict[str, Any]:
    documents = state.get("filtered_documents", [])
    logger.info("[AdaptiveRAG] generate_answer start grounded_chunks=%s", len(documents))
    await safe_emit(
        emit,
        f"[generation] generating answer from {len(documents)} grounded chunks.",
        len(documents),
        "generation",
    )

    evidence_result = await generate_citation_evidence(
        state["question"],
        documents,
        required_concepts=state.get("query_intent", {}).get("required_concepts", []),
        covered_concepts=state.get("covered_concepts", []),
        intent_type=state.get("query_intent", {}).get("intent_type", "single"),
    )
    answer_with_citations = evidence_result["answer_with_citations"]
    answer = evidence_result["answer_text"]

    state["answer"] = answer
    state["citations"] = evidence_result["citations"]
    state["answer_with_citations"] = answer_with_citations
    state["raw_sources"] = evidence_result["raw_sources"]
    state["evidence_nodes"] = evidence_result["evidence_nodes"]
    state["covered_concepts"] = evidence_result["covered_concepts"]
    state["missing_concepts"] = evidence_result["missing_concepts"]
    state["result_reason"] = (
        partial_coverage_reason if evidence_result["coverage_status"] == "partial" else None
    )
    logger.info(
        "[AdaptiveRAG] generate_answer completed answer_len=%s citation_blocks=%s cited_chunk_ids=%s covered_concepts=%s missing_concepts=%s coverage_status=%s",
        len(answer),
        len(answer_with_citations),
        [citation.get("chunk_id") for citation in state.get("citations", [])],
        state.get("covered_concepts", []),
        state.get("missing_concepts", []),
        evidence_result["coverage_status"],
    )
    return state
