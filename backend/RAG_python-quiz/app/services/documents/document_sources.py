from __future__ import annotations

from typing import Any, Dict, List

from langchain_community.document_loaders import AsyncHtmlLoader
from langchain_community.document_transformers import MarkdownifyTransformer

from app.utils.ingest_errors import DocumentIngestError


async def load_markdown(url: str, *, loader_cls=AsyncHtmlLoader, transformer_cls=MarkdownifyTransformer):
    docs_html = await loader_cls(url).aload()
    return transformer_cls().transform_documents(docs_html)


def is_pdf_upload(filename: str, mimetype: str) -> bool:
    normalized_type = (mimetype or "").lower()
    normalized_name = (filename or "").lower()
    return normalized_type == "application/pdf" or normalized_name.endswith(".pdf")


def build_pdf_page_docs(filename: str, pages_text: List[str]) -> List[Dict[str, Any]]:
    docs = [
        {"pageContent": text, "metadata": {"source": filename, "pageNumber": page_number}}
        for page_number, text in enumerate(pages_text, start=1)
        if text.strip() and len(text.strip()) > 10
    ]
    if not docs:
        raise DocumentIngestError(
            code="EMPTY_DOCUMENT",
            message="No extractable text was found in this PDF.",
        )
    return docs


def markdown_documents_to_text(docs_markdown) -> str:
    if not docs_markdown:
        raise RuntimeError("Fetched website content was empty.")
    markdown = "\n\n".join(
        (getattr(doc, "page_content", "") or "") for doc in docs_markdown
    ).strip()
    if not markdown:
        raise RuntimeError("Fetched website content was empty.")
    return markdown


def split_docs_to_chunks(docs: List[Dict[str, Any]], *, text_splitter) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for doc in docs:
        for chunk in text_splitter.split_text(doc["pageContent"]):
            chunks.append({"pageContent": chunk, "metadata": doc["metadata"]})
    return chunks


def split_markdown_to_chunks(markdown: str, url: str, *, text_splitter) -> List[Dict[str, Any]]:
    return [
        {"pageContent": part, "metadata": {"source": url, "pageNumber": index + 1}}
        for index, part in enumerate(text_splitter.split_text(markdown))
    ]
