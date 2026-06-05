from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

GenerateStructuredJson = Callable[..., Awaitable[Dict[str, Any]]]


def build_generation_grading_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "grounded": {"type": "string", "enum": ["yes", "no"]},
            "coverage_status": {"type": "string", "enum": ["full", "partial", "insufficient"]},
            "reason": {"type": "string"},
        },
        "required": ["grounded", "coverage_status", "reason"],
    }


def build_generation_grading_prompt(state: Dict[str, Any], *, max_doc_preview_chars: int) -> str:
    documents = state.get("filtered_documents", [])
    document_preview = "\n\n".join(
        [
            f"[Document {idx}] {doc.get('source')} p.{doc.get('page')}\n{(doc.get('text') or '')[:max_doc_preview_chars]}"
            for idx, doc in enumerate(documents, start=1)
        ]
    )
    return f"""
You are verifying a RAG answer.
Return grounded=yes only if the answer is supported by the provided documents.
Return coverage_status=full only if the answer addresses all required concepts.
Return coverage_status=partial only if the answer correctly covers the supported concepts, explicitly names the missing concepts, and does not invent unsupported details.
Return coverage_status=insufficient if the answer misses supported content or overclaims beyond the documents.

Question:
{state["question"]}

Required concepts:
{state.get("query_intent", {}).get("required_concepts", [])}

Covered concepts from retrieval:
{state.get("covered_concepts", [])}

Missing concepts from retrieval:
{state.get("missing_concepts", [])}

Answer:
{(state.get("answer") or "").strip()}

Documents:
{document_preview}
"""


async def grade_generation_node(
    state: Dict[str, Any],
    emit,
    *,
    generate_structured_json: GenerateStructuredJson,
    safe_emit,
    unreliable_reason: str,
    partial_coverage_reason: str,
    max_doc_preview_chars: int,
    logger,
) -> Dict[str, Any]:
    answer = (state.get("answer") or "").strip()
    answer_with_citations = state.get("answer_with_citations", [])
    logger.info(
        "[AdaptiveRAG] grade_generation start answer_len=%s grounded_chunks=%s",
        len(answer),
        len(state.get("filtered_documents", [])),
    )
    await safe_emit(
        emit,
        "[grader] checking whether the generated answer is grounded and answers the question.",
        event_type="grader",
    )

    if not answer or (not answer_with_citations and not state.get("citations")):
        state["result_reason"] = unreliable_reason
        logger.warning(
            "[AdaptiveRAG] grade_generation rejected due to missing answer_or_citations answer_len=%s citation_blocks=%s",
            len(answer),
            len(answer_with_citations),
        )
        return state

    try:
        result = await generate_structured_json(
            build_generation_grading_prompt(state, max_doc_preview_chars=max_doc_preview_chars),
            build_generation_grading_schema(),
            operation_name="Adaptive RAG grade generation",
            temperature=0.0,
        )
    except Exception as err:
        logger.warning("[AdaptiveRAG] generation grading failed; accepting answer: %s", err)
        return state

    coverage_status = result.get("coverage_status")
    if result.get("grounded") == "yes" and coverage_status in {"full", "partial"}:
        missing_concepts = state.get("missing_concepts", [])
        state["result_reason"] = (
            partial_coverage_reason if missing_concepts or coverage_status == "partial" else None
        )
        logger.info(
            "[AdaptiveRAG] grade_generation accepted grounded=%s coverage_status=%s reason=%r",
            result.get("grounded"),
            coverage_status,
            (result.get("reason") or "")[:200],
        )
        return state

    state["result_reason"] = unreliable_reason
    logger.warning(
        "[AdaptiveRAG] grade_generation rejected grounded=%s coverage_status=%s reason=%r",
        result.get("grounded"),
        result.get("coverage_status"),
        (result.get("reason") or "")[:200],
    )
    return state
