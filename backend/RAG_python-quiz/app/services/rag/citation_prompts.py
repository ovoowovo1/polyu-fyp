from __future__ import annotations

import re
from typing import List, Sequence

from llama_index.core.schema import NodeWithScore

MAX_SOURCE_EXCERPT_CHARS = 800


def format_source_excerpt(text: str) -> str:
    flattened = re.sub(r"\s+", " ", (text or "").strip())
    if len(flattened) <= MAX_SOURCE_EXCERPT_CHARS:
        return flattened or "[No excerpt available]"
    return f"{flattened[:MAX_SOURCE_EXCERPT_CHARS].rstrip()}..."


def format_sources_for_prompt(source_nodes: Sequence[NodeWithScore]) -> str:
    if not source_nodes:
        return "[No grounded sources available]"

    formatted_sources: List[str] = []
    for index, source_node in enumerate(source_nodes, start=1):
        metadata = source_node.node.metadata or {}
        formatted_sources.append(
            "\n".join(
                [
                    f"[{index}] {metadata.get('source') or 'Unknown source'} | page {metadata.get('page') or 'Unknown page'} | chunk_id={metadata.get('chunk_id') or source_node.node.node_id or 'unknown'}",
                    format_source_excerpt(getattr(source_node.node, "text", "") or ""),
                ]
            )
        )

    return "\n\n".join(formatted_sources)


def build_markdown_synthesis_prompt(
    question: str,
    draft_answer: str,
    source_nodes: Sequence[NodeWithScore],
    *,
    required_concepts: Sequence[str],
    covered_concepts: Sequence[str],
    missing_concepts: Sequence[str],
    intent_type: str,
) -> str:
    coverage_summary = [
        f"Required concepts: {', '.join(required_concepts) if required_concepts else '(none)'}",
        f"Covered concepts: {', '.join(covered_concepts) if covered_concepts else '(none)'}",
        f"Missing concepts: {', '.join(missing_concepts) if missing_concepts else '(none)'}",
    ]
    comparison_instruction = (
        "If this is a comparison question, organize the answer around grounded similarities and differences."
        if intent_type == "comparison"
        else "Use the structure that best explains the grounded answer."
    )
    limitation_instruction = (
        "Include a short `## Limits` section that explicitly names the missing concepts and says the selected documents do not provide enough reliable information about them."
        if missing_concepts
        else "Do not add a limitations section unless the sources are genuinely incomplete."
    )

    return "\n".join(
        [
            "Rewrite the grounded answer into a fuller English Markdown response.",
            "",
            "Rules:",
            "- Use only the grounded draft answer and source excerpts below.",
            "- Do not use external knowledge, guesses, or unsupported conclusions.",
            "- Use Markdown headings, bullet lists, and Markdown tables when they improve clarity.",
            "- If the user explicitly asks for a table, comparison table, or table-style comparison, the final answer must include a Markdown table unless the grounded draft answer is empty.",
            "- Do not refuse to create a table only because the sources are partially incomplete. Instead, create the table using supported information and mark unsupported cells as `Not provided by the selected documents`.",
            "- Every factual paragraph, bullet item, or table row must end with one or more bracket citations like [1] or [1, 2].",
            "- For Markdown tables, put citations inside the relevant cells or in a final `Sources` column.",
            "- Only use citation numbers that appear in the provided source list.",
            "- Keep citations inline. Do not add a references section or code fences.",
            f"- {comparison_instruction}",
            f"- {limitation_instruction}",
            "",
            "Question:",
            question.strip(),
            "",
            "Grounded draft answer:",
            draft_answer.strip() or "(empty grounded draft answer)",
            "",
            "Coverage context:",
            *coverage_summary,
            "",
            "Available citation sources:",
            format_sources_for_prompt(source_nodes),
        ]
    )
