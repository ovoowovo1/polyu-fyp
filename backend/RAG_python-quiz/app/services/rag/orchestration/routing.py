from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from app.services.rag.retrieval import intent as retrieval_intent
from app.services.rag.language import DEFAULT_NOTICES

GenerateStructuredJson = Callable[..., Awaitable[Dict[str, Any]]]


def build_combined_planner_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["retrieve", "reject"]},
            "answer_language": {"type": "string", "minLength": 1},
            "messages": {"type": "object", "properties": {name: {"type": "string", "minLength": 1} for name in DEFAULT_NOTICES}, "required": list(DEFAULT_NOTICES), "additionalProperties": False},
            "reason": {"type": "string"},
            "query_intent": retrieval_intent.build_query_intent_schema(),
        },
        "required": ["decision", "reason", "query_intent", "answer_language", "messages"],
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
Every subqueries/search_queries concept must be null or an EXACT entry in required_concepts.
Use null for combined or contextual queries; never invent a combined concept label.
Create a separate query for each required concept, preserving the exact concept label.
Keep the plan focused on what is actually asked. A broad question does not require an
exhaustive survey of every possible subtopic; do not invent additional required facets.
Describe answer_language as a non-empty language name, following explicit user requests first,
otherwise the question's language. Support any language; use Traditional Chinese for Chinese.
Never infer answer language from source documents or UI. Supply short messages in that language:
insufficient_evidence (selected documents lack evidence), verification_unavailable (verification
service could not complete; retry later), omitted_content (unsupported content was omitted). Do not answer the question. Return only JSON matching the supplied schema.

Question:
{question}
"""


def _fallback_planner_result(question: str) -> Dict[str, Any]:
    return {
        "decision": "retrieve",
        "reason": "planner fallback",
        "answer_language": None,
        "messages": {},
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
        language = result.get("answer_language")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("planner answer_language must be a non-empty string")
        messages = result.get("messages", {})
        if not isinstance(messages, dict) or any(not isinstance(v, str) or not v.strip() for v in messages.values()):
            raise ValueError("planner messages must contain non-empty strings")
        return {
            "decision": decision,
            "reason": reason.strip(),
            "answer_language": language.strip(),
            "messages": {name: messages[name].strip() for name in DEFAULT_NOTICES if name in messages},
            "query_intent": query_intent,
        }
    except Exception as err:
        logger.warning("[AdaptiveRAG] route and query planner fallback to retrieve: %s", err)
        return _fallback_planner_result(question)
