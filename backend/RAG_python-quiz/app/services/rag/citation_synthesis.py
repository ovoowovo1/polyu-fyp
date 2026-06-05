from __future__ import annotations

from typing import Sequence

from llama_index.core.schema import NodeWithScore

from app.logger import get_logger
from app.services.rag.citation_markdown import normalize_markdown_answer, strip_inline_citations
from app.services.rag.citation_prompts import build_markdown_synthesis_prompt

logger = get_logger(__name__)


async def synthesize_markdown_answer(
    question: str,
    draft_answer: str,
    source_nodes: Sequence[NodeWithScore],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
    missing_concepts: Sequence[str] = (),
    intent_type: str = "single",
    generate_text_completion_func,
) -> str:
    if not draft_answer.strip():
        return ""

    prompt = build_markdown_synthesis_prompt(
        question,
        draft_answer,
        source_nodes,
        required_concepts=required_concepts,
        covered_concepts=covered_concepts,
        missing_concepts=missing_concepts,
        intent_type=intent_type,
    )
    answer = await generate_text_completion_func(
        prompt,
        operation_name="Citation evidence markdown synthesis",
        system_prompt=(
            "You are a grounded RAG answer writer. "
            "Return English Markdown only, with inline bracket citations that match the provided source numbers."
        ),
        temperature=0.0,
    )
    return normalize_markdown_answer(answer)


async def synthesize_markdown_answer_or_draft(
    question: str,
    grounded_draft: str,
    source_nodes: Sequence[NodeWithScore],
    *,
    required: Sequence[str],
    covered: Sequence[str],
    missing: Sequence[str],
    intent_type: str,
    generate_text_completion_func,
) -> str:
    try:
        return await synthesize_markdown_answer(
            question,
            grounded_draft,
            source_nodes,
            required_concepts=required,
            covered_concepts=covered,
            missing_concepts=missing,
            intent_type=intent_type,
            generate_text_completion_func=generate_text_completion_func,
        )
    except Exception as err:
        logger.warning("[CitationEvidence] markdown synthesis fallback to citation query draft: %s", err)
        return grounded_draft


def build_default_citation_suffix(source_nodes: Sequence[NodeWithScore], *, limit: int = 2) -> str:
    if not source_nodes:
        return ""
    count = min(len(source_nodes), max(1, limit))
    joined_numbers = ", ".join(str(index) for index in range(1, count + 1))
    return f" [{joined_numbers}]"


def build_missing_concept_disclaimer(missing_concepts: Sequence[str]) -> str:
    if not missing_concepts:
        return ""
    if len(missing_concepts) == 1:
        return f"The selected documents do not provide enough reliable information about {missing_concepts[0]}."
    return (
        "The selected documents do not provide enough reliable information about "
        + ", ".join(missing_concepts[:-1])
        + f", and {missing_concepts[-1]}."
    )


def ensure_missing_concept_section(
    answer_text: str,
    missing_concepts: Sequence[str],
    source_nodes: Sequence[NodeWithScore],
) -> str:
    disclaimer = build_missing_concept_disclaimer(missing_concepts)
    if not disclaimer:
        return answer_text

    if disclaimer.casefold() in strip_inline_citations(answer_text).casefold():
        return answer_text

    cited_disclaimer = f"{disclaimer}{build_default_citation_suffix(source_nodes)}".rstrip()
    if not answer_text.strip():
        return f"## Limits\n{cited_disclaimer}".strip()
    return f"{answer_text.rstrip()}\n\n## Limits\n{cited_disclaimer}".strip()


def build_synthesis_question(
    question: str,
    intent_type: str,
    required_concepts: Sequence[str],
    covered_concepts: Sequence[str],
    missing_concepts: Sequence[str],
) -> str:
    if intent_type == "comparison" and required_concepts:
        comparison_instruction = (
            "Focus on grounded differences and comparisons between the required concepts. "
            "Prefer direct comparisons over incidental mentions."
        )
    else:
        comparison_instruction = ""

    if missing_concepts:
        return (
            f"{question}\n\n"
            "Answer only with information supported by the provided sources.\n"
            f"Covered concepts: {', '.join(covered_concepts)}.\n"
            f"Missing evidence concepts: {', '.join(missing_concepts)}.\n"
            "Explain the grounded concepts first, then explicitly say that the selected documents do not provide enough reliable information about the missing concepts. "
            f"{comparison_instruction} "
            "Do not invent unsupported details."
        )

    if required_concepts:
        coverage_instruction = (
            "Answer only with information supported by the provided sources.\n"
            f"Make sure the answer covers all of these concepts when supported: {', '.join(required_concepts)}."
        )
        if comparison_instruction:
            coverage_instruction = f"{coverage_instruction} {comparison_instruction}"
        return (
            f"{question}\n\n"
            f"{coverage_instruction}"
        )

    return question.strip()
