from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

from llama_index.core.base.response.schema import Response
from llama_index.core.llms import CompletionResponse, CustomLLM, LLMMetadata
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.schema import MetadataMode, NodeWithScore

from app.logger import get_logger
from app.services.ai.llm.text_completion import generate_text_completion
from app.services.rag import citation_adapters, citation_markdown, citation_prompts, citation_synthesis
from app.services.rag.citation_types import (
    CitationEvidenceResult,
    EvidenceCitation,
    EvidenceNode,
    EvidenceSource,
)
from app.services.rag.rag_shared import (
    build_retrieval_evidence as shared_build_retrieval_evidence,
)
from app.utils.api_key_manager import get_default_llm_model_name, get_llm_client
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)

DEFAULT_CITATION_CHUNK_SIZE = citation_adapters.DEFAULT_CITATION_CHUNK_SIZE
DEFAULT_NUM_OUTPUT = 1024
MAX_SOURCE_EXCERPT_CHARS = citation_prompts.MAX_SOURCE_EXCERPT_CHARS

# Compatibility aliases for older unit tests/imports.
StaticNodeRetriever = citation_adapters.StaticNodeRetriever
_build_llamaindex_nodes = citation_adapters.build_llamaindex_nodes
_normalize_text_spacing = citation_markdown.normalize_text_spacing
_citation_reference = citation_markdown.citation_reference
_split_inline_citation_numbers = citation_markdown.split_inline_citation_numbers
_strip_inline_citations = citation_markdown.strip_inline_citations
_normalize_markdown_answer = citation_markdown.normalize_markdown_answer
_split_list_items = citation_markdown.split_list_items
_split_markdown_blocks = citation_markdown.split_markdown_blocks
_fallback_citation_payload = citation_markdown.fallback_citation_payload
build_answer_with_citations = citation_markdown.build_answer_with_citations
_build_cited_answer_payload = citation_markdown.build_cited_answer_payload
_format_source_excerpt = citation_prompts.format_source_excerpt
_format_sources_for_prompt = citation_prompts.format_sources_for_prompt
_build_markdown_synthesis_prompt = citation_prompts.build_markdown_synthesis_prompt
_build_default_citation_suffix = citation_synthesis.build_default_citation_suffix
_ensure_missing_concept_section = citation_synthesis.ensure_missing_concept_section
_build_synthesis_question = citation_synthesis.build_synthesis_question
_build_missing_concept_disclaimer = citation_synthesis.build_missing_concept_disclaimer


def build_retrieval_evidence(
    documents: Sequence[Dict[str, Any]],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
) -> Dict[str, Any]:
    return shared_build_retrieval_evidence(
        documents,
        required_concepts=required_concepts,
        covered_concepts=covered_concepts,
    )


def _build_empty_citation_result(
    *,
    required: List[str],
    covered: List[str],
    missing: List[str],
    raw_sources: List[EvidenceSource],
    evidence_nodes: List[EvidenceNode],
) -> CitationEvidenceResult:
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
    return await citation_synthesis.synthesize_markdown_answer(
        question,
        draft_answer,
        source_nodes,
        required_concepts=required_concepts,
        covered_concepts=covered_concepts,
        missing_concepts=missing_concepts,
        intent_type=intent_type,
        generate_text_completion_func=generate_text_completion,
    )


async def _synthesize_markdown_answer_or_draft(
    question: str,
    grounded_draft: str,
    source_nodes: Sequence[NodeWithScore],
    *,
    required: Sequence[str],
    covered: Sequence[str],
    missing: Sequence[str],
    intent_type: str,
) -> str:
    return await citation_synthesis.synthesize_markdown_answer_or_draft(
        question,
        grounded_draft,
        source_nodes,
        required=required,
        covered=covered,
        missing=missing,
        intent_type=intent_type,
        generate_text_completion_func=generate_text_completion,
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


def _build_completed_citation_result(
    *,
    answer_text: str,
    citations: List[EvidenceCitation],
    raw_sources: List[EvidenceSource],
    evidence_nodes: List[EvidenceNode],
    answer_with_citations: List[Dict[str, Any]],
    required: List[str],
    covered: List[str],
    missing: List[str],
) -> CitationEvidenceResult:
    return {
        "answer_text": answer_text,
        "citations": citations,
        "raw_sources": raw_sources,
        "evidence_nodes": evidence_nodes,
        "answer_with_citations": answer_with_citations,
        "required_concepts": required,
        "covered_concepts": covered,
        "missing_concepts": missing,
        "coverage_status": "partial" if missing else "complete",
    }


async def generate_citation_evidence(
    question: str,
    documents: Sequence[Dict[str, Any]],
    *,
    required_concepts: Sequence[str] = (),
    covered_concepts: Sequence[str] = (),
    intent_type: str = "single",
) -> CitationEvidenceResult:
    retrieval_evidence = shared_build_retrieval_evidence(
        documents,
        required_concepts=required_concepts,
        covered_concepts=covered_concepts,
    )
    normalized_docs = retrieval_evidence["raw_sources"]
    required = retrieval_evidence["required_concepts"]
    covered = retrieval_evidence["covered_concepts"]
    missing = retrieval_evidence["missing_concepts"]
    raw_sources = retrieval_evidence["raw_sources"]
    evidence_nodes = retrieval_evidence["evidence_nodes"]

    if not normalized_docs or (required and not covered):
        return _build_empty_citation_result(
            required=required,
            covered=covered,
            missing=missing,
            raw_sources=raw_sources,
            evidence_nodes=evidence_nodes,
        )

    synthesis_question = _build_synthesis_question(question, intent_type, required, covered, missing)
    response = await asyncio.to_thread(_run_citation_query, synthesis_question, normalized_docs)
    grounded_draft = _normalize_markdown_answer(response.response or "")
    synthesized_answer = await _synthesize_markdown_answer_or_draft(
        question,
        grounded_draft,
        response.source_nodes,
        required=required,
        covered=covered,
        missing=missing,
        intent_type=intent_type,
    )
    answer_text, citations, answer_with_citations = _build_cited_answer_payload(
        _ensure_missing_concept_section(synthesized_answer or grounded_draft, missing, response.source_nodes),
        response.source_nodes,
    )

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
    return _build_completed_citation_result(
        answer_text=answer_text,
        citations=citations,
        raw_sources=raw_sources,
        evidence_nodes=evidence_nodes,
        answer_with_citations=answer_with_citations,
        required=required,
        covered=covered,
        missing=missing,
    )
