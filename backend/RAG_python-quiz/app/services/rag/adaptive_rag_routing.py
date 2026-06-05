from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

GenerateStructuredJson = Callable[..., Awaitable[Dict[str, Any]]]


def build_route_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["retrieve", "reject"]},
            "reason": {"type": "string"},
        },
        "required": ["decision", "reason"],
    }


def build_route_prompt(question: str) -> str:
    return f"""
Decide whether the following user question is suitable for a document-grounded RAG answer.

Context:
- The system is only allowed to answer from the user's selected documents.
- It must not give an open-ended general-knowledge answer.
- Reject only when the question clearly requires external/current/personal information or is not plausibly answerable from study materials.
- If the question could reasonably be answered from course notes, lecture slides, reports, or selected files, choose retrieve.

Question:
{question}
"""


async def route_question_node(
    state: Dict[str, Any],
    emit,
    *,
    generate_structured_json: GenerateStructuredJson,
    safe_emit,
    logger,
) -> Dict[str, Any]:
    logger.info(
        "[AdaptiveRAG] route_question start question=%r selected_files=%s",
        state["question"][:160],
        len(state.get("selected_file_ids", [])),
    )
    await safe_emit(
        emit,
        "[router] assessing whether the question should be answered only from the selected documents.",
        event_type="router",
    )
    try:
        result = await generate_structured_json(
            build_route_prompt(state["question"]),
            build_route_schema(),
            operation_name="Adaptive RAG route question",
            temperature=0.0,
        )
        decision = result.get("decision", "retrieve")
    except Exception as err:
        logger.warning("[AdaptiveRAG] route_question fallback to retrieve: %s", err)
        decision = "retrieve"

    state["route_decision"] = decision
    logger.info("[AdaptiveRAG] route_question decision=%s", decision)
    return state
