from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from app.services.documents import document_sources, ingestion_payloads
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError


def validate_pdf_upload(filename: str, mimetype: str, is_pdf_upload) -> None:
    if not is_pdf_upload(filename, mimetype):
        raise DocumentIngestError(
            code="UNSUPPORTED_MEDIA_TYPE",
            message="Only PDF uploads are supported.",
            details=f"filename={filename}, mimetype={mimetype or '<empty>'}",
        )


def validate_supported_upload(filename: str, mimetype: str, is_supported_upload) -> None:
    if not is_supported_upload(filename, mimetype):
        raise DocumentIngestError(
            code="UNSUPPORTED_MEDIA_TYPE",
            message="Only PDF and image uploads are supported.",
            details=f"filename={filename}, mimetype={mimetype or '<empty>'}",
        )


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def duplicate_file_result(existing: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message": "File already exists. Reusing the existing document.",
        "fileId": existing["id"],
        "isNew": False,
        "chunksCount": 0,
        "entitiesCount": 0,
        "relationshipsCount": 0,
    }


def duplicate_website_result(existing: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message": "Website already exists. Reusing the existing document.",
        "fileId": existing["id"],
        "isNew": False,
    }


async def extract_pdf_pages(content: bytes, extract_pdf_content_by_page):
    try:
        return await extract_pdf_content_by_page(content)
    except Exception as err:
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to extract text from the PDF.",
            details=str(err),
        ) from err


def build_pdf_chunks(filename: str, pages_text, text_splitter):
    image_chunks = []
    for page in pages_text:
        if not isinstance(page, dict):
            continue
        for image in page.get("images", []):
            image_chunks.extend(
                document_sources.build_image_chunks(
                    filename,
                    image["data"],
                    image["mimetype"],
                    page_number=int(page.get("pageNumber") or 1),
                    image_index=int(image.get("imageIndex") or 1),
                )
            )

    try:
        docs = document_sources.build_pdf_page_docs(filename, pages_text)
        text_chunks = document_sources.split_docs_to_chunks(docs, text_splitter=text_splitter)
    except DocumentIngestError:
        if not image_chunks:
            raise
        text_chunks = []

    return text_chunks + image_chunks


def build_image_chunks(filename: str, content: bytes, mimetype: str):
    return document_sources.build_image_chunks(filename, content, mimetype)


async def embed_document_chunks(chunks, embed_chunks_for_storage):
    try:
        return await embed_chunks_for_storage(chunks)
    except EmbeddingProviderError:
        raise
    except Exception as err:
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to generate embeddings for this document.",
            details=str(err),
        ) from err


def build_chunks_for_db(chunks, primary_vectors, fallback_vectors, *, assemble_chunks_for_db, get_settings):
    return assemble_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        fallback_column=get_settings().embedding_fallback_column,
    )


def build_and_store_document(
    *,
    name: str,
    size: int,
    file_hash: str,
    mimetype: str,
    class_id: Optional[str],
    user_id: Optional[str],
    chunks_for_db,
    pg_service,
):
    document_data = ingestion_payloads.build_document_data(
        name=name,
        size=size,
        file_hash=file_hash,
        mimetype=mimetype,
        class_id=class_id,
    )
    return pg_service.create_graph_from_document(document_data, chunks_for_db, user_id=user_id)


def build_uploaded_result(name: str, file_id: str, chunks_count: int) -> Dict[str, Any]:
    return {
        "message": f"Uploaded {name}",
        "fileId": file_id,
        "chunksCount": chunks_count,
        "entitiesCount": 0,
        "relationshipsCount": 0,
        "isNew": True,
    }


def markdown_hash_and_size(markdown: str) -> tuple[str, int]:
    encoded = markdown.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def split_website_chunks(markdown: str, url: str, text_splitter):
    return document_sources.split_markdown_to_chunks(markdown, url, text_splitter=text_splitter)


async def publish_progress_event(publish_progress, client_id: Optional[str], done: int, total: int) -> None:
    await publish_progress(client_id, {"type": "progress", "done": done, "total": total})


async def publish_finished_event(publish_progress, client_id: Optional[str], file_id: str, chunks_count: int) -> None:
    await publish_progress(
        client_id,
        {"type": "finished", "status": "success", "fileId": file_id, "chunks": chunks_count},
    )
