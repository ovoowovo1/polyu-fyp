from __future__ import annotations

from typing import Any, Dict, List, Sequence

from llama_index.core.base.response.schema import Response
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle, TextNode

from app.services.rag.rag_shared import build_raw_sources

DEFAULT_CITATION_CHUNK_SIZE = 8192


class StaticNodeRetriever(BaseRetriever):
    def __init__(self, nodes: Sequence[NodeWithScore]):
        super().__init__()
        self._nodes = list(nodes)

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        del query_bundle
        return list(self._nodes)


def build_llamaindex_nodes(documents: Sequence[Dict[str, Any]]) -> List[NodeWithScore]:
    normalized_docs = build_raw_sources(documents)
    nodes: List[NodeWithScore] = []
    for index, (doc, original) in enumerate(zip(normalized_docs, documents), start=1):
        node = TextNode(
            text=doc.get("content") or "",
            id_=doc.get("chunkId") or f"citation-node-{index}",
            metadata={
                "file_id": doc.get("fileId"),
                "chunk_id": doc.get("chunkId"),
                "source": doc.get("source"),
                "page": doc.get("pageNumber"),
                "image_data": original.get("image_data"),
                "image_mimetype": original.get("image_mimetype"),
            },
        )
        nodes.append(NodeWithScore(node=node, score=doc.get("score")))
    return nodes


def run_citation_query(
    question: str,
    documents: Sequence[Dict[str, Any]],
    *,
    llm,
    query_engine_cls=CitationQueryEngine,
    citation_chunk_size: int = DEFAULT_CITATION_CHUNK_SIZE,
) -> Response:
    retriever = StaticNodeRetriever(build_llamaindex_nodes(documents))
    query_engine = query_engine_cls(
        retriever=retriever,
        llm=llm,
        citation_chunk_size=citation_chunk_size,
        citation_chunk_overlap=0,
        metadata_mode=MetadataMode.NONE,
    )
    return query_engine.query(question.strip())
