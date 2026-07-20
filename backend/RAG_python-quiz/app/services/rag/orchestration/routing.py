from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from app.services.rag.retrieval import intent as retrieval_intent

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


def build_combined_planner_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["retrieve", "reject"]},
            "reason": {"type": "string"},
            "query_intent": retrieval_intent.build_query_intent_schema(),
        },
        "required": ["decision", "reason", "query_intent"],
        "additionalProperties": False,
    }


def build_combined_planner_prompt(question: str) -> str:
    return f"""
You are the routing and multilingual retrieval planner for a course-document RAG system.

First decide whether the question can plausibly be answered from the selected course documents.
Reject only questions that clearly require external/current/personal information or are not
plausibly answerable from course materials. If it could be answered from lecture notes,
slides, reports, or selected files, choose retrieve.

Then create a complete query_intent retrieval plan. Understand Traditional Chinese,
Cantonese-style wording, English, and mixed Chinese-English technical questions.
Use open semantic labels for intent_type and query_kind. Identify required concepts and
produce all useful search_queries. Preserve scenario facts, constraints, numbers, units,
time ranges, data references, formulas, comparison context, and important technical terms.
Do not answer the question. Return only JSON matching the supplied schema.

Question:
{question}
"""


def _fallback_planner_result(question: str) -> Dict[str, Any]:
    return {
        "decision": "retrieve",
        "reason": "planner fallback",
        "query_intent": retrieval_intent._build_single_query_intent(question),
    }


async def plan_question(
    question: str,
    *,
    generate_structured_json: GenerateStructuredJson,
    logger,
) -> Dict[str, Any]:
    try:
        result = await generate_structured_json(
            build_combined_planner_prompt(question),
            build_combined_planner_schema(),
            operation_name="Adaptive RAG route and query plan",
            temperature=0.0,
        )
        if not isinstance(result, dict):
            raise ValueError("planner result must be an object")
        decision = result.get("decision")
        reason = result.get("reason")
        query_intent = retrieval_intent._normalize_query_intent(result.get("query_intent"))
        if decision not in {"retrieve", "reject"}:
            raise ValueError(f"invalid route decision: {decision!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("planner reason must be a non-empty string")
        return {
            "decision": decision,
            "reason": reason.strip(),
            "query_intent": query_intent,
        }
    except Exception as err:
        logger.warning("[AdaptiveRAG] route and query planner fallback to retrieve: %s", err)
        return _fallback_planner_result(question)


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
    planner_result = state.get("planner_result")
    if not isinstance(planner_result, dict) or not planner_result:
        planner_result = await plan_question(
            state["question"],
            generate_structured_json=generate_structured_json,
            logger=logger,
        )
    try:
        decision = planner_result["decision"]
        reason = planner_result["reason"]
        query_intent = retrieval_intent._normalize_query_intent(planner_result["query_intent"])
        if decision not in {"retrieve", "reject"}:
            raise ValueError(f"invalid route decision: {decision!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("planner reason must be a non-empty string")
    except Exception as err:
        logger.warning("[AdaptiveRAG] malformed planner state; using fallback: %s", err)
        planner_result = _fallback_planner_result(state["question"])
        decision = planner_result["decision"]
        reason = planner_result["reason"]
        query_intent = planner_result["query_intent"]

    state["route_decision"] = decision
    state["route_reason"] = reason
    state["query_intent"] = query_intent
    state["planner_result"] = planner_result
    state["classified_query"] = state.get("current_query", state["question"])
    logger.info(
        "[AdaptiveRAG] route_question decision=%s reason=%r intent_type=%s required_concepts=%s",
        decision,
        reason,
        query_intent["intent_type"],
        query_intent["required_concepts"],
    )
    return state
