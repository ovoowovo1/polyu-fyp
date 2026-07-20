from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from app.services.rag.shared.helpers import normalize_concepts

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
You are a multilingual intent classifier and retrieval planner for a course-document RAG system.

You understand Traditional Chinese, natural Cantonese-style wording, English,
and mixed Chinese-English technical questions.

Your task is to classify the user's question and produce a retrieval plan.
Do not answer the user's question.

Classification fields:

1. intent_type
Identify the primary information need using a short semantic label.

Common labels include:
- definition
- comparison
- explanation
- application
- scenario_analysis
- quantitative
- procedure
- troubleshooting

You may use another concise label when none of these accurately describe the question.

2. concept_scope
- single: the question mainly concerns one technical concept.
- multiple: the question requires separate evidence about two or more technical concepts.

3. required_concepts
Extract the actual technical concepts mentioned or implied by the question.
Preserve their original technical names where possible.

Do not split one concept merely because its name contains spaces,
punctuation, slashes, hyphens, or conjunctions.

Retrieval planning rules:

- Create subqueries for independently retrievable concepts or evidence needs.
- Include every retrieval query in search_queries.
- Each search query must have a concise query_kind describing its purpose.
- Use clear query_kind labels such as scenario_context or formula_support when
  the question requires case facts or quantitative/formula evidence.
- Preserve important terminology from the user's original language.
- Do not introduce concepts that are not needed to answer the question.

For comparison questions:
- retrieve concept-specific evidence for each compared concept;
- retrieve direct comparison, differences, trade-offs, or selection criteria;
- do not rely only on documents that mention both terms without comparing them.

For multi-concept definition questions:
- retrieve definition evidence for each concept separately;
- add a combined query only when their relationship is relevant.

For scenario or application questions:
- preserve relevant case facts, constraints, assumptions, goals,
  and domain context in the search queries.

For quantitative questions:
- preserve all numbers, units, time ranges, variables, and referenced data;
- retrieve formula, method, and data context separately when necessary.

Return only valid JSON matching the supplied schema.
Do not include Markdown, explanations, or an answer to the question.

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
