"""Public entrypoints for the document-grounded RAG pipeline."""

from app.services.rag.index import run_adaptive_rag_stream

__all__ = ["run_adaptive_rag_stream"]
