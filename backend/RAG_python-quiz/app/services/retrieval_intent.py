from __future__ import annotations

import re
from typing import List, Optional, Sequence, TypedDict

from app.services.rag_shared import normalize_concepts

_MULTI_CONCEPT_SPLIT_RE = re.compile(r"\s*(?:/|,|\band\b|\bvs\.?\b|\bversus\b)\s*", re.IGNORECASE)
_COMPARISON_HEAD_PATTERNS = [
    re.compile(r"^(?:what\s+is|what's)\s+(?:the\s+)?(?:difference|differences|different)\s+(?:between|in)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:the\s+)?(?:difference|differences|different)\s+(?:between|in)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:compare|contrast)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:comparison)\s+(?:between|of)\s+(.+)$", re.IGNORECASE),
]
_DEFINITION_HEAD_PATTERN = re.compile(r"^(?:what\s+is|what\s+are|define|explain)\s+(.+)$", re.IGNORECASE)
_LEADING_NOISE_RE = re.compile(
    r"^(?:the\s+)?(?:difference|differences|different|comparison|compare|contrast)\s+(?:between|in|of)\s+",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


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


def _canonicalize_known_concept(concept: str) -> str:
    return re.sub(r"\s+", " ", (concept or "").strip())


def _clean_concept_fragment(fragment: str) -> str:
    cleaned = re.sub(r"\s+", " ", (fragment or "").strip().strip("?.!,:;")).strip()
    cleaned = _LEADING_NOISE_RE.sub("", cleaned)
    cleaned = re.sub(r"^(?:between|in|of)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = _LEADING_ARTICLE_RE.sub("", cleaned)
    return _canonicalize_known_concept(cleaned)


def _extract_comparison_tail(question: str) -> str:
    cleaned = " ".join((question or "").split())
    for pattern in _COMPARISON_HEAD_PATTERNS:
        match = pattern.match(cleaned)
        if match:
            return match.group(1)
    if re.search(r"\bvs\.?\b|\bversus\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    return ""


def _extract_multi_concepts(question: str) -> tuple[str, List[str]]:
    cleaned = " ".join((question or "").split())
    comparison_tail = _extract_comparison_tail(cleaned)
    if comparison_tail:
        concepts = normalize_concepts(_MULTI_CONCEPT_SPLIT_RE.split(comparison_tail), normalizer=_clean_concept_fragment)
        if len(concepts) >= 2:
            return "comparison", concepts

    definition_match = _DEFINITION_HEAD_PATTERN.match(cleaned)
    if definition_match:
        concepts = normalize_concepts(
            _MULTI_CONCEPT_SPLIT_RE.split(definition_match.group(1)),
            normalizer=_clean_concept_fragment,
        )
        if len(concepts) >= 2:
            return "definition_multi", concepts

    return "single", []


def _definition_query_for_concept(concept: str) -> str:
    return f"definition of {concept}"


def _comparison_query_for_concepts(concepts: Sequence[str]) -> str:
    if len(concepts) == 2:
        return f"difference between {concepts[0]} and {concepts[1]} databases"
    return f"comparison between {' and '.join(concepts)}"


def _build_query_intent(cleaned: str, intent_type: str, concepts: Sequence[str]) -> QueryIntent:
    normalized_concepts = normalize_concepts(concepts, normalizer=_clean_concept_fragment)
    if intent_type == "single" or not normalized_concepts:
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

    if intent_type == "comparison":
        comparison_query = _comparison_query_for_concepts(normalized_concepts)
        subqueries: List[QuerySearchSpec] = [
            {
                "label": concept,
                "query": _definition_query_for_concept(concept),
                "concept": concept,
                "query_kind": "concept_support",
            }
            for concept in normalized_concepts
        ]
        search_queries: List[QuerySearchSpec] = [
            {
                "label": "comparison",
                "query": comparison_query,
                "concept": None,
                "query_kind": "comparison",
            }
        ]
        if len(normalized_concepts) == 2:
            search_queries.append(
                {
                    "label": "vs comparison",
                    "query": f"{normalized_concepts[0]} vs {normalized_concepts[1]} comparison",
                    "concept": None,
                    "query_kind": "comparison",
                }
            )
        search_queries.extend(subqueries)
        return {
            "mode": "multi",
            "intent_type": "comparison",
            "required_concepts": normalized_concepts,
            "subqueries": subqueries,
            "search_queries": search_queries,
        }

    subqueries = [
        {
            "label": concept,
            "query": _definition_query_for_concept(concept),
            "concept": concept,
            "query_kind": "concept_definition",
        }
        for concept in normalized_concepts
    ]
    search_queries = list(subqueries)
    search_queries.append(
        {
            "label": "combined definition",
            "query": f"what is {' and '.join(normalized_concepts)}",
            "concept": None,
            "query_kind": "combined_definition",
        }
    )
    return {
        "mode": "multi",
        "intent_type": "definition_multi",
        "required_concepts": normalized_concepts,
        "subqueries": subqueries,
        "search_queries": search_queries,
    }


def analyze_query_intent(
    question: str,
    *,
    fallback_required_concepts: Sequence[str] = (),
    fallback_intent_type: str | None = None,
) -> QueryIntent:
    cleaned = " ".join((question or "").split()).strip()
    intent_type, concepts = _extract_multi_concepts(cleaned)
    if intent_type != "single":
        return _build_query_intent(cleaned, intent_type, concepts)

    fallback_concepts = normalize_concepts(fallback_required_concepts, normalizer=_clean_concept_fragment)
    if fallback_concepts and fallback_intent_type in {"definition_multi", "comparison"}:
        return _build_query_intent(cleaned, fallback_intent_type, fallback_concepts)

    return _build_query_intent(cleaned, "single", [])
