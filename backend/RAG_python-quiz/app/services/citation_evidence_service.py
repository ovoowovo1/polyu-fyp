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
from app.utils.api_key_manager import get_default_llm_model_name, get_llm_client
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)


DEFAULT_CITATION_CHUNK_SIZE = 8192
DEFAULT_NUM_OUTPUT = 1024
_INLINE_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SENTENCE_SPAN_PATTERN = re.compile(r".*?(?:\n+|[.!?][\"')\]]*\s*|$)", re.S)


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


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _normalize_text_spacing(text: str) -> str:
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


def _normalize_concepts(concepts: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for concept in concepts:
        normalized = re.sub(r"\s+", " ", (concept or "").strip().strip("?.!,:;")).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def normalize_retrieved_documents(documents: Sequence[Dict[str, Any]]) -> List[EvidenceSource]:
    normalized: List[EvidenceSource] = []
    for doc in documents:
        normalized.append(
            {
                "content": (doc.get("content") or doc.get("text") or "").strip(),
                "source": doc.get("source") or doc.get("document_name") or "Unknown source",
                "pageNumber": (
                    doc.get("pageNumber")
                    or doc.get("page")
                    or doc.get("page_start")
                    or doc.get("pageStart")
                    or "Unknown page"
                ),
                "score": _float_or_none(
                    doc.get("score") or doc.get("relevance_score") or doc.get("rrf_score")
                ),
                "fileId": doc.get("fileId") or doc.get("fileid"),
                "chunkId": doc.get("chunkId") or doc.get("chunkid"),
            }
        )
    return normalized


def build_raw_sources(documents: Sequence[Dict[str, Any]]) -> List[EvidenceSource]:
    return normalize_retrieved_documents(documents)


def build_evidence_nodes(documents: Sequence[Dict[str, Any]]) -> List[EvidenceNode]:
    normalized_docs = normalize_retrieved_documents(documents)
    return [
        {
            "node_id": doc.get("chunkId") or f"evidence-node-{index}",
            "file_id": doc.get("fileId"),
            "chunk_id": doc.get("chunkId"),
            "source": doc.get("source") or "Unknown source",
            "page": doc.get("pageNumber") or "Unknown page",
            "text": doc.get("content") or "",
            "score": doc.get("score"),
        }
        for index, doc in enumerate(normalized_docs, start=1)
    ]


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
    required = _normalize_concepts(required_concepts)
    covered = _derive_covered_concepts(documents, covered_concepts)
    missing = [concept for concept in required if concept not in covered]
    return {
        "raw_sources": build_raw_sources(documents),
        "evidence_nodes": build_evidence_nodes(documents),
        "required_concepts": required,
        "covered_concepts": covered,
        "missing_concepts": missing,
    }


def _fallback_citation_payload(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[List[EvidenceCitation], List[Dict[str, Any]]]:
    normalized_answer = _normalize_text_spacing(answer_text)
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
    return _normalize_text_spacing(_INLINE_CITATION_PATTERN.sub("", text))


def _sentence_spans(answer_text: str) -> List[str]:
    return [match.group(0) for match in _SENTENCE_SPAN_PATTERN.finditer(answer_text) if match.group(0)]


def build_answer_with_citations(
    answer_text: str,
    source_nodes: Sequence[NodeWithScore],
) -> tuple[str, List[EvidenceCitation], List[Dict[str, Any]]]:
    if not answer_text:
        return "", [], []

    content_segments: List[Dict[str, Any]] = []
    citations: List[EvidenceCitation] = []
    seen_chunks: set[str] = set()

    for raw_segment in _sentence_spans(answer_text):
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

    clean_answer = _strip_inline_citations(answer_text)
    answer_with_citations = [{"content_segments": content_segments}] if content_segments else []
    return clean_answer, citations, answer_with_citations


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
    answer_text, citations, answer_with_citations = build_answer_with_citations(
        response.response or "",
        response.source_nodes,
    )
    if answer_text and not answer_with_citations:
        citations, answer_with_citations = _fallback_citation_payload(answer_text, response.source_nodes)

    if missing:
        disclaimer = _build_missing_concept_disclaimer(missing)
        if disclaimer and disclaimer.casefold() not in answer_text.casefold():
            answer_text = f"{answer_text}\n\n{disclaimer}".strip()

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
