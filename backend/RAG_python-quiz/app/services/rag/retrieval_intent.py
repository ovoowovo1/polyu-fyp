from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from app.services.rag.rag_shared import normalize_concepts

logger = logging.getLogger(__name__)

MAX_INTENT_CONCEPTS = 8
MAX_INTENT_SEARCH_QUERIES = 12

GenerateStructuredJson = Callable[..., Awaitable[Dict[str, Any]]]


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


def build_query_intent_schema() -> Dict[str, Any]:
    query_spec_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "query": {"type": "string"},
            "concept": {"type": ["string", "null"]},
            "query_kind": {"type": "string", "minLength": 1},
        },
        "required": ["label", "query", "concept", "query_kind"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["single", "multi"]},
            "intent_type": {"type": "string", "minLength": 1},
            "required_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_INTENT_CONCEPTS,
            },
            "subqueries": {
                "type": "array",
                "items": query_spec_schema,
                "maxItems": MAX_INTENT_SEARCH_QUERIES,
            },
            "search_queries": {
                "type": "array",
                "items": query_spec_schema,
                "minItems": 1,
                "maxItems": MAX_INTENT_SEARCH_QUERIES,
            },
        },
        "required": ["mode", "intent_type", "required_concepts", "subqueries", "search_queries"],
        "additionalProperties": False,
    }


def build_query_intent_prompt(question: str) -> str:
    return f"""
You are the multilingual intent classifier and retrieval planner for a course-document RAG system.

Understand Traditional Chinese, natural Cantonese-style wording, English, and mixed Chinese-English technical questions.
Classify the user's retrieval intent and produce a complete search plan. Do not answer the question.

Intent rules:
- single: the question asks about one topic or does not require separate concept searches.
- definition_multi: the question asks to explain or define two or more separate concepts.
- comparison: the question compares two or more concepts, including natural forms such as:
  - "SQL \u540c NoSQL \u6709\u5481\u5206\u5225\uff1f"
  - "SQL \u548c NoSQL \u54ea\u500b\u6bd4\u8f03\u9069\u5408\uff1f"
  - "\u8acb\u6bd4\u8f03 SQL \u8207 NoSQL"
  - "What are the trade-offs between SQL and NoSQL?"

Planning rules:
- Treat intent_type and query_kind as short, extensible semantic labels. Use a useful label for the question instead of following a fixed enum.
- Examples include comparison, definition_multi, scenario, quantitative, scenario_context, data_context, and formula_support; these are examples, not an exhaustive list.
- Extract the actual technical concepts as required_concepts; preserve their original names where possible.
- Do not split a single concept merely because it contains spaces, punctuation, or an English conjunction.
- Create subqueries for concept-specific support and search_queries for every retrieval query needed.
- For comparison questions, include comparison context and concept-specific support when useful.
- For definition questions, include one definition query per concept and a combined definition query when useful.
- For scenario questions, preserve the case facts, constraints, assumptions, and domain context in the search queries.
- For quantitative questions, preserve all numbers, units, time ranges, data references, and relevant formulas; use query kinds such as data_context or formula_support when useful.
- A single retrieval mode may contain multiple search_queries when the question needs different kinds of supporting evidence.
- Query text may remain in the user's language; preserve important Chinese and English technical terms.
- Return only JSON matching the supplied schema.

User question:
<question>
{question}
</question>
"""


def _canonicalize_known_concept(concept: str) -> str:
    return re.sub(r"\s+", " ", (concept or "").strip())


def _clean_concept_fragment(fragment: str) -> str:
    """Normalize model-produced concepts without language-specific parsing."""
    cleaned = re.sub(
        r"\s+",
        " ",
        (fragment or "").strip().strip("?.!,:;\uff0c\u3002\uff01\uff1f\uff1a\uff1b"),
    ).strip()
    return _canonicalize_known_concept(cleaned)


def _build_single_query_intent(question: str) -> QueryIntent:
    cleaned = " ".join((question or "").split()).strip()
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


def _normalize_query_spec(raw_spec: Any, required_concepts: List[str]) -> QuerySearchSpec:
    if not isinstance(raw_spec, dict):
        raise ValueError("query spec must be an object")

    label = raw_spec.get("label")
    query = raw_spec.get("query")
    concept = raw_spec.get("concept")
    query_kind = raw_spec.get("query_kind")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("query spec label must be a non-empty string")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query spec query must be a non-empty string")
    if concept is not None and not isinstance(concept, str):
        raise ValueError("query spec concept must be a string or null")
    if not isinstance(query_kind, str) or not query_kind.strip():
        raise ValueError("query spec query_kind must be a non-empty string")

    normalized_concept = _clean_concept_fragment(concept) if concept is not None else None
    if normalized_concept and normalized_concept.casefold() not in {
        value.casefold() for value in required_concepts
    }:
        raise ValueError(f"query spec concept is not a required concept: {normalized_concept!r}")
    return {
        "label": label.strip(),
        "query": " ".join(query.split()).strip(),
        "concept": normalized_concept,
        "query_kind": query_kind.strip().casefold(),
    }


def _normalize_query_intent(result: Any) -> QueryIntent:
    if not isinstance(result, dict):
        raise ValueError("intent result must be an object")

    intent_type = result.get("intent_type")
    mode = result.get("mode")
    raw_concepts = result.get("required_concepts")
    raw_subqueries = result.get("subqueries")
    raw_search_queries = result.get("search_queries")
    if not isinstance(intent_type, str) or not intent_type.strip():
        raise ValueError("intent_type must be a non-empty string")
    intent_type = intent_type.strip().casefold()
    if mode not in {"single", "multi"}:
        raise ValueError(f"mode is invalid: {mode!r}")
    if not isinstance(raw_concepts, list) or not all(isinstance(value, str) for value in raw_concepts):
        raise ValueError("required_concepts must be a string array")
    if not isinstance(raw_subqueries, list) or not isinstance(raw_search_queries, list):
        raise ValueError("subqueries and search_queries must be arrays")
    if len(raw_concepts) > MAX_INTENT_CONCEPTS:
        raise ValueError("too many required concepts")
    if len(raw_subqueries) > MAX_INTENT_SEARCH_QUERIES or len(raw_search_queries) > MAX_INTENT_SEARCH_QUERIES:
        raise ValueError("too many search queries")

    required_concepts = normalize_concepts(raw_concepts, normalizer=_clean_concept_fragment)
    if len(raw_search_queries) < 1:
        raise ValueError("intent plan requires at least one search query")

    subqueries = [_normalize_query_spec(spec, required_concepts) for spec in raw_subqueries]
    search_queries = [_normalize_query_spec(spec, required_concepts) for spec in raw_search_queries]

    return {
        "mode": mode,
        "intent_type": intent_type,
        "required_concepts": required_concepts,
        "subqueries": subqueries,
        "search_queries": search_queries,
    }


async def classify_query_intent(
    question: str,
    *,
    generate_structured_json_func: GenerateStructuredJson | None = None,
) -> QueryIntent:
    """Classify a query with an LLM and return a validated retrieval plan."""
    if generate_structured_json_func is None:
        from app.services.ai.llm.structured_json import generate_structured_json

        generate_structured_json_func = generate_structured_json

    cleaned = " ".join((question or "").split()).strip()
    try:
        result = await generate_structured_json_func(
            build_query_intent_prompt(cleaned),
            build_query_intent_schema(),
            operation_name="Adaptive RAG classify query intent",
            temperature=0.0,
        )
        return _normalize_query_intent(result)
    except Exception as err:
        logger.warning("[AdaptiveRAG] query intent classification failed; using single query: %s", err)
        return _build_single_query_intent(cleaned)
