from __future__ import annotations

from app.logger import get_logger
from app.services.rag import retrieval_intent
from app.services.rag.adaptive_types import AdaptiveRetrievalState, EventCallback
from app.services.rag.rag_shared import safe_emit

logger = get_logger(__name__)


async def rewrite_query_node(
    state: AdaptiveRetrievalState,
    emit: EventCallback,
    *,
    max_rewrite_attempts: int,
    log_prefix: str,
    generate_structured_json_func,
) -> AdaptiveRetrievalState:
    rewrite_count = state.get("rewrite_count", 0) + 1
    state["rewrite_count"] = rewrite_count
    query_intent = state.get("query_intent") or retrieval_intent.analyze_query_intent(state.get("original_question", ""))
    logger.info(
        "[%s] rewrite_query start attempt=%s original_question=%r current_query=%r intent_type=%s required_concepts=%s",
        log_prefix,
        rewrite_count,
        state.get("original_question", "")[:160],
        state.get("current_query", "")[:160],
        query_intent.get("intent_type"),
        query_intent.get("required_concepts", []),
    )

    await safe_emit(
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
        result = await generate_structured_json_func(
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
    state["query_intent"] = retrieval_intent.analyze_query_intent(
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
    await safe_emit(
        emit,
        f"[rewrite] rewritten query: {state['current_query']}",
        state["current_query"],
        "rewrite",
    )
    return state
