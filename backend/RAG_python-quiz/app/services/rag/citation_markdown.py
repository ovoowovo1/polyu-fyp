from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from llama_index.core.schema import NodeWithScore

from app.services.rag.citation_types import EvidenceCitation

INLINE_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
BLOCK_SEPARATOR_PATTERN = re.compile(r"\n\s*\n+")
HEADER_PATTERN = re.compile(r"^\s*#{1,6}\s+")
LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)")


def normalize_text_spacing(text: str) -> str:
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


def citation_reference(source_nodes: Sequence[NodeWithScore], citation_number: int) -> Optional[EvidenceCitation]:
    if citation_number < 1 or citation_number > len(source_nodes):
        return None

    metadata = source_nodes[citation_number - 1].node.metadata or {}
    chunk_id = metadata.get("chunk_id") or source_nodes[citation_number - 1].node.node_id
    if not chunk_id:
        return None

    return {
        "chunk_id": str(chunk_id),
        "file_id": metadata.get("file_id"),
        "source": metadata.get("source") or "Unknown source",
        "page": metadata.get("page") or "Unknown page",
    }


def split_inline_citation_numbers(raw_numbers: str) -> List[int]:
    seen: set[int] = set()
    ordered: List[int] = []
    for value in raw_numbers.split(","):
        citation_number = int(value.strip())
        if citation_number in seen:
            continue
        seen.add(citation_number)
        ordered.append(citation_number)
    return ordered


def strip_inline_citations(text: str) -> str:
    cleaned = INLINE_CITATION_PATTERN.sub("", text.replace("\r\n", "\n"))
    normalized_lines = [normalize_text_spacing(line).rstrip() for line in cleaned.splitlines()]
    return "\n".join(normalized_lines).strip()


def normalize_markdown_answer(text: str) -> str:
    if not text:
        return ""

    normalized_lines: List[str] = []
    previous_blank = False
    for raw_line in text.replace("\r\n", "\n").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line.strip())
        previous_blank = False

    return "\n".join(normalized_lines).strip()


def split_list_items(lines: Sequence[str]) -> List[str]:
    items: List[List[str]] = []
    current: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if LIST_ITEM_PATTERN.match(line):
            if current:
                items.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
            continue
        current = [line]

    if current:
        items.append(current)

    return ["\n".join(item).strip() for item in items if item]


def split_markdown_blocks(answer_text: str) -> List[str]:
    normalized = normalize_markdown_answer(answer_text)
    if not normalized:
        return []

    blocks: List[str] = []
    pending_headers: List[str] = []

    for raw_block in BLOCK_SEPARATOR_PATTERN.split(normalized):
        block = raw_block.strip()
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        header_lines: List[str] = []
        while lines and HEADER_PATTERN.match(lines[0]):
            header_lines.append(lines.pop(0))

        if header_lines and not lines:
            pending_headers.extend(header_lines)
            continue

        if pending_headers:
            header_lines = [*pending_headers, *header_lines]
            pending_headers = []

        if lines and all(LIST_ITEM_PATTERN.match(line) for line in lines):
            list_items = split_list_items(lines)
            for index, item in enumerate(list_items):
                prefix = "\n".join(header_lines) if index == 0 and header_lines else ""
                blocks.append(f"{prefix}\n{item}".strip() if prefix else item)
            continue

        combined_lines = [*header_lines, *lines]
        if combined_lines:
            blocks.append("\n".join(combined_lines).strip())

    return blocks


def fallback_citation_payload(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[List[EvidenceCitation], List[Dict[str, Any]]]:
    normalized_answer = strip_inline_citations(answer_text)
    if not normalized_answer:
        return [], []

    fallback_reference = citation_reference(source_nodes, 1)
    if fallback_reference is None:
        return [], []

    return (
        [fallback_reference],
        [
            {
                "content_segments": [
                    {
                        "segment_text": normalized_answer,
                        "source_references": [{"file_chunk_id": fallback_reference["chunk_id"]}],
                    }
                ]
            }
        ],
    )


def build_answer_with_citations(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[str, List[EvidenceCitation], List[Dict[str, Any]]]:
    if not answer_text:
        return "", [], []

    normalized_answer = normalize_markdown_answer(answer_text)
    content_segments: List[Dict[str, Any]] = []
    citations: List[EvidenceCitation] = []
    seen_chunks: set[str] = set()

    for raw_segment in split_markdown_blocks(normalized_answer):
        segment_text = strip_inline_citations(raw_segment)
        source_references = []
        seen_segment_chunks: set[str] = set()

        for match in INLINE_CITATION_PATTERN.finditer(raw_segment):
            for ref_number in split_inline_citation_numbers(match.group(1)):
                citation = citation_reference(source_nodes, ref_number)
                if citation is None:
                    continue

                chunk_id = citation["chunk_id"]
                if chunk_id not in seen_segment_chunks:
                    source_references.append({"file_chunk_id": chunk_id})
                    seen_segment_chunks.add(chunk_id)

                if chunk_id not in seen_chunks:
                    citations.append(citation)
                    seen_chunks.add(chunk_id)

        if segment_text and source_references:
            content_segments.append(
                {
                    "segment_text": segment_text,
                    "source_references": source_references,
                }
            )

    answer_with_citations = [{"content_segments": content_segments}] if content_segments else []
    return normalized_answer, citations, answer_with_citations


def build_cited_answer_payload(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[str, List[EvidenceCitation], List[Dict[str, Any]]]:
    normalized_answer, citations, answer_with_citations = build_answer_with_citations(answer_text, source_nodes)
    if normalized_answer and not answer_with_citations:
        citations, answer_with_citations = fallback_citation_payload(normalized_answer, source_nodes)
    return normalized_answer, citations, answer_with_citations
