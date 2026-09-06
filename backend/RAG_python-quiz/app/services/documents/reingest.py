from app.utils.model_usage import model_workflow
import asyncio

from psycopg2.extras import execute_values

from app.services.cache import redis_cache, studio_cache
from app.services.core.exceptions import ValidationServiceError
from app.services.documents import document_service as documents
from app.services.documents import ingestion_steps
from app.services.pg.pg_db import _get_conn
from app.services.pg.pg_retrieval_documents import get_reingest_document, replace_document_chunks
from app.services.realtime.progress_bus import publish_progress


@model_workflow("ReingestUsage")
async def reingest_pdf(file_id: str, user_id: str, filename: str, content: bytes,
                       mimetype: str, client_id: str | None = None) -> dict:
    connection = lambda: _get_conn(user_id)
    original = await asyncio.to_thread(get_reingest_document, get_conn=connection, file_id=file_id, user_id=user_id)
    if not documents._is_pdf_upload(filename, mimetype) or not content.startswith(b"%PDF-"):
        raise ValidationServiceError("Please select the original PDF file.")
    file_hash = ingestion_steps.content_hash(content)
    if original["hash"] != file_hash:
        raise ValidationServiceError("Original PDF hash does not match this document.")

    async def progress(done, stage):
        await publish_progress(client_id, {"type": "progress", "done": done, "total": 4, "stage": stage})

    await progress(1, "extracting")
    pages = await ingestion_steps.extract_pdf_pages(content, documents.extract_pdf_content_by_page)
    chunks = ingestion_steps.build_pdf_chunks(original["name"], pages, documents.text_splitter)
    await progress(2, "embedding")
    vectors = await ingestion_steps.embed_document_chunks(chunks, documents._embed_chunks_for_storage)
    if len(vectors) != len(chunks) or any(not vector for vector in vectors):
        raise ValidationServiceError("Embedding results are incomplete; document was not changed.")
    prepared = ingestion_steps.build_chunks_for_db(chunks, vectors,
        assemble_chunks_for_db=documents._assemble_chunks_for_db)
    await progress(3, "replacing")
    result = await asyncio.to_thread(replace_document_chunks, get_conn=connection, execute_values=execute_values,
        file_id=file_id, user_id=user_id, expected_hash=file_hash, chunks=prepared)
    await redis_cache.invalidate_namespaces(studio_cache.files_list_namespace(),
        studio_cache.file_detail_namespace(file_id), studio_cache.chunk_source_namespace(), studio_cache.rag_retrieval_namespace())
    await progress(4, "complete")
    await publish_progress(client_id, {"type": "finished", **result})
    return result
