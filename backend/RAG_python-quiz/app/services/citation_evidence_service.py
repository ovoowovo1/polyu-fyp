from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Sequence, TypedDict

from llama_index.core.base.response.schema import Response
from llama_index.core.llms import CompletionResponse, CustomLLM, LLMMetadata
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle, TextNode

from app.logger import get_logger
from app.services.ai_service import generate_text_completion
from app.services.rag_shared import (
    build_evidence_nodes as shared_build_evidence_nodes,
    build_raw_sources as shared_build_raw_sources,
    build_retrieval_evidence as shared_build_retrieval_evidence,
    normalize_concepts as shared_normalize_concepts,
)
from app.utils.api_key_manager import get_default_llm_model_name, get_llm_client
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


DEFAULT_CITATION_CHUNK_SIZE = 8192
DEFAULT_NUM_OUTPUT = 1024
_INLINE_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_BLOCK_SEPARATOR_PATTERN = re.compile(r"\n\s*\n+")
_HEADER_PATTERN = re.compile(r"^\s*#{1,6}\s+")
_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)")
MAX_SOURCE_EXCERPT_CHARS = 800


class EvidenceCitation(TypedDict):
    chunk_id: str
    file_id: Optional[str]
    source: str
    page: Any


class EvidenceSource(TypedDict):
    content: str
    source: str
    pageNumber: Any
    score: Optional[float]
    fileId: Optional[str]
    chunkId: Optional[str]


class EvidenceNode(TypedDict):
    node_id: str
    file_id: Optional[str]
    chunk_id: Optional[str]
    source: str
    page: Any
    text: str
    score: Optional[float]


class CitationEvidenceResult(TypedDict):
    answer_text: str
    citations: List[EvidenceCitation]
    raw_sources: List[EvidenceSource]
    evidence_nodes: List[EvidenceNode]
    answer_with_citations: List[Dict[str, Any]]
    required_concepts: List[str]
    covered_concepts: List[str]
    missing_concepts: List[str]
    coverage_status: str


def _normalize_text_spacing(text: str) -> str:
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


def _normalize_concepts(concepts: Sequence[str]) -> List[str]:
    return shared_normalize_concepts(concepts)


def normalize_retrieved_documents(documents: Sequence[Dict[str, Any]]) -> List[EvidenceSource]:
    return shared_build_raw_sources(documents)


def build_raw_sources(documents: Sequence[Dict[str, Any]]) -> List[EvidenceSource]:
    return shared_build_raw_sources(documents)


def build_evidence_nodes(documents: Sequence[Dict[str, Any]]) -> List[EvidenceNode]:
    return shared_build_evidence_nodes(documents)


def _derive_covered_concepts(
    documents: Sequence[Dict[str, Any]],
    explicit_covered_concepts: Sequence[str],
) -> List[str]:
    if explicit_covered_concepts:
        return _normalize_concepts(explicit_covered_concepts)

    derived: List[str] = []
    for doc in documents:
        derived.extend(doc.get("covered_concepts", []))
    return _normalize_concepts(derived)


def build_retrieval_evidence(
    documents: Sequence[Dict[str, Any]],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
) -> Dict[str, Any]:
    return shared_build_retrieval_evidence(
        documents,
        required_concepts=required_concepts,
        covered_concepts=_derive_covered_concepts(documents, covered_concepts),
    )


def _fallback_citation_payload(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[List[EvidenceCitation], List[Dict[str, Any]]]:
    normalized_answer = _strip_inline_citations(answer_text)
    if not normalized_answer:
        return [], []

    fallback_reference = _citation_reference(source_nodes, 1)
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


class StaticNodeRetriever(BaseRetriever):
    def __init__(self, nodes: Sequence[NodeWithScore]):
        super().__init__()
        self._nodes = list(nodes)

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        del query_bundle
        return list(self._nodes)


class OpenAICompatibleCustomLLM(CustomLLM):
    model_name: str = ""
    temperature: float = 0.0
    context_window: int = 32768
    num_output: int = DEFAULT_NUM_OUTPUT
    api_key: Optional[str] = None

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self.num_output,
            model_name=self.model_name or "openai-compatible",
        )

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        del formatted
        client = get_llm_client(self.api_key)
        response = client.chat.completions.create(
            model=self.model_name or get_default_llm_model_name(),
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
        )
        text = extract_chat_completion_text(response, "LlamaIndex citation synthesis").strip()
        return CompletionResponse(text=text, raw=response)

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        completion = self.complete(prompt, formatted=formatted, **kwargs)
        yield CompletionResponse(text=completion.text, delta=completion.text, raw=completion.raw)


def _build_llamaindex_nodes(documents: Sequence[Dict[str, Any]]) -> List[NodeWithScore]:
    normalized_docs = normalize_retrieved_documents(documents)
    nodes: List[NodeWithScore] = []
    for index, doc in enumerate(normalized_docs, start=1):
        node = TextNode(
            text=doc.get("content") or "",
            id_=doc.get("chunkId") or f"citation-node-{index}",
            metadata={
                "file_id": doc.get("fileId"),
                "chunk_id": doc.get("chunkId"),
                "source": doc.get("source"),
                "page": doc.get("pageNumber"),
            },
        )
        nodes.append(NodeWithScore(node=node, score=doc.get("score")))
    return nodes


def _citation_reference(source_nodes: Sequence[NodeWithScore], citation_number: int) -> Optional[EvidenceCitation]:
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


def _split_inline_citation_numbers(raw_numbers: str) -> List[int]:
    seen: set[int] = set()
    ordered: List[int] = []
    for value in raw_numbers.split(","):
        citation_number = int(value.strip())
        if citation_number in seen:
            continue
        seen.add(citation_number)
        ordered.append(citation_number)
    return ordered


def _strip_inline_citations(text: str) -> str:
    cleaned = _INLINE_CITATION_PATTERN.sub("", text.replace("\r\n", "\n"))
    normalized_lines = [_normalize_text_spacing(line).rstrip() for line in cleaned.splitlines()]
    return "\n".join(normalized_lines).strip()


def _normalize_markdown_answer(text: str) -> str:
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


def _split_list_items(lines: Sequence[str]) -> List[str]:
    items: List[List[str]] = []
    current: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _LIST_ITEM_PATTERN.match(line):
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


def _split_markdown_blocks(answer_text: str) -> List[str]:
    normalized = _normalize_markdown_answer(answer_text)
    if not normalized:
        return []

    blocks: List[str] = []
    pending_headers: List[str] = []

    for raw_block in _BLOCK_SEPARATOR_PATTERN.split(normalized):
        block = raw_block.strip()
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        header_lines: List[str] = []
        while lines and _HEADER_PATTERN.match(lines[0]):
            header_lines.append(lines.pop(0))

        if header_lines and not lines:
            pending_headers.extend(header_lines)
            continue

        if pending_headers:
            header_lines = [*pending_headers, *header_lines]
            pending_headers = []

        if lines and all(_LIST_ITEM_PATTERN.match(line) for line in lines):
            list_items = _split_list_items(lines)
            for index, item in enumerate(list_items):
                prefix = "\n".join(header_lines) if index == 0 and header_lines else ""
                blocks.append(f"{prefix}\n{item}".strip() if prefix else item)
            continue

        combined_lines = [*header_lines, *lines]
        if combined_lines:
            blocks.append("\n".join(combined_lines).strip())

    return blocks


def _format_source_excerpt(text: str) -> str:
    flattened = re.sub(r"\s+", " ", (text or "").strip())
    if len(flattened) <= MAX_SOURCE_EXCERPT_CHARS:
        return flattened or "[No excerpt available]"
    return f"{flattened[:MAX_SOURCE_EXCERPT_CHARS].rstrip()}..."


def _format_sources_for_prompt(source_nodes: Sequence[NodeWithScore]) -> str:
    if not source_nodes:
        return "[No grounded sources available]"

    formatted_sources: List[str] = []
    for index, source_node in enumerate(source_nodes, start=1):
        metadata = source_node.node.metadata or {}
        formatted_sources.append(
            "\n".join(
                [
                    f"[{index}] {metadata.get('source') or 'Unknown source'} | page {metadata.get('page') or 'Unknown page'} | chunk_id={metadata.get('chunk_id') or source_node.node.node_id or 'unknown'}",
                    _format_source_excerpt(getattr(source_node.node, "text", "") or ""),
                ]
            )
        )

    return "\n\n".join(formatted_sources)


def _build_markdown_synthesis_prompt(
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
            _format_sources_for_prompt(source_nodes),
        ]
    )


async def synthesize_markdown_answer(
    question: str,
    draft_answer: str,
    source_nodes: Sequence[NodeWithScore],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
    missing_concepts: Sequence[str] = (),
    intent_type: str = "single",
) -> str:
    if not draft_answer.strip():
        return ""

    prompt = _build_markdown_synthesis_prompt(
        question,
        draft_answer,
        source_nodes,
        required_concepts=required_concepts,
        covered_concepts=covered_concepts,
        missing_concepts=missing_concepts,
        intent_type=intent_type,
    )
    answer = await generate_text_completion(
        prompt,
        operation_name="Citation evidence markdown synthesis",
        system_prompt=(
            "You are a grounded RAG answer writer. "
            "Return English Markdown only, with inline bracket citations that match the provided source numbers."
        ),
        temperature=0.0,
    )
    return _normalize_markdown_answer(answer)


def _build_default_citation_suffix(source_nodes: Sequence[NodeWithScore], *, limit: int = 2) -> str:
    if not source_nodes:
        return ""
    count = min(len(source_nodes), max(1, limit))
    joined_numbers = ", ".join(str(index) for index in range(1, count + 1))
    return f" [{joined_numbers}]"


def _ensure_missing_concept_section(
    answer_text: str,
    missing_concepts: Sequence[str],
    source_nodes: Sequence[NodeWithScore],
) -> str:
    disclaimer = _build_missing_concept_disclaimer(missing_concepts)
    if not disclaimer:
        return answer_text

    if disclaimer.casefold() in _strip_inline_citations(answer_text).casefold():
        return answer_text

    cited_disclaimer = f"{disclaimer}{_build_default_citation_suffix(source_nodes)}".rstrip()
    if not answer_text.strip():
        return f"## Limits\n{cited_disclaimer}".strip()
    return f"{answer_text.rstrip()}\n\n## Limits\n{cited_disclaimer}".strip()


def build_answer_with_citations(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[str, List[EvidenceCitation], List[Dict[str, Any]]]:
    if not answer_text:
        return "", [], []

    normalized_answer = _normalize_markdown_answer(answer_text)
    content_segments: List[Dict[str, Any]] = []
    citations: List[EvidenceCitation] = []
    seen_chunks: set[str] = set()

    for raw_segment in _split_markdown_blocks(normalized_answer):
        segment_text = _strip_inline_citations(raw_segment)
        source_references = []
        seen_segment_chunks: set[str] = set()

        for match in _INLINE_CITATION_PATTERN.finditer(raw_segment):
            for ref_number in _split_inline_citation_numbers(match.group(1)):
                citation = _citation_reference(source_nodes, ref_number)
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


def _build_synthesis_question(
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


def _build_missing_concept_disclaimer(missing_concepts: Sequence[str]) -> str:
    if not missing_concepts:
        return ""
    if len(missing_concepts) == 1:
        return f"The selected documents do not provide enough reliable information about {missing_concepts[0]}."
    return (
        "The selected documents do not provide enough reliable information about "
        + ", ".join(missing_concepts[:-1])
        + f", and {missing_concepts[-1]}."
    )


def _run_citation_query(question: str, documents: Sequence[Dict[str, Any]]) -> Response:
    llm = OpenAICompatibleCustomLLM(model_name=get_default_llm_model_name())
    retriever = StaticNodeRetriever(_build_llamaindex_nodes(documents))
    query_engine = CitationQueryEngine(
        retriever=retriever,
        llm=llm,
        citation_chunk_size=DEFAULT_CITATION_CHUNK_SIZE,
        citation_chunk_overlap=0,
        metadata_mode=MetadataMode.NONE,
    )
    return query_engine.query(question.strip())


async def generate_citation_evidence(
    question: str,
    documents: Sequence[Dict[str, Any]],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
    intent_type: str = "single",
) -> CitationEvidenceResult:
    normalized_docs = normalize_retrieved_documents(documents)
    required = _normalize_concepts(required_concepts)
    covered = _derive_covered_concepts(documents, covered_concepts)
    missing = [concept for concept in required if concept not in covered]
    raw_sources = build_raw_sources(normalized_docs)
    evidence_nodes = build_evidence_nodes(normalized_docs)

    if not normalized_docs or (required and not covered):
        return {
            "answer_text": "",
            "citations": [],
            "raw_sources": raw_sources,
            "evidence_nodes": evidence_nodes,
            "answer_with_citations": [],
            "required_concepts": required,
            "covered_concepts": covered,
            "missing_concepts": missing,
            "coverage_status": "none" if required else "empty",
        }

    synthesis_question = _build_synthesis_question(question, intent_type, required, covered, missing)
    response = await asyncio.to_thread(_run_citation_query, synthesis_question, normalized_docs)
    grounded_draft = _normalize_markdown_answer(response.response or "")
    try:
        synthesized_answer = await synthesize_markdown_answer(
            question,
            grounded_draft,
            response.source_nodes,
            required_concepts=required,
            covered_concepts=covered,
            missing_concepts=missing,
            intent_type=intent_type,
        )
    except Exception as err:
        logger.warning("[CitationEvidence] markdown synthesis fallback to citation query draft: %s", err)
        synthesized_answer = grounded_draft

    answer_text, citations, answer_with_citations = build_answer_with_citations(
        _ensure_missing_concept_section(synthesized_answer or grounded_draft, missing, response.source_nodes),
        response.source_nodes,
    )
    if answer_text and not answer_with_citations:
        citations, answer_with_citations = _fallback_citation_payload(answer_text, response.source_nodes)

    coverage_status = "partial" if missing else "complete"
    logger.info(
        "[CitationEvidence] built answer_len=%s citations=%s source_nodes=%s covered_concepts=%s missing_concepts=%s coverage_status=%s",
        len(answer_text),
        len(citations),
        len(response.source_nodes),
        covered,
        missing,
        coverage_status,
    )
    return {
        "answer_text": answer_text,
        "citations": citations,
        "raw_sources": raw_sources,
        "evidence_nodes": evidence_nodes,
        "answer_with_citations": answer_with_citations,
        "required_concepts": required,
        "covered_concepts": covered,
        "missing_concepts": missing,
        "coverage_status": coverage_status,
    }
