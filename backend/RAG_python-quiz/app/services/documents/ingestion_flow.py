from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.documents import document_sources, ingestion_steps
from app.utils.ingest_errors import DocumentIngestError


async def ingest_document(
    *,
    filename: str,
    content: bytes,
    size: int,
    mimetype: str,
    class_id: Optional[str],
    user_id: Optional[str],
    is_pdf_upload,
    is_supported_upload,
    is_image_upload,
    extract_pdf_content_by_page,
    text_splitter,
    embed_chunks_for_storage,
    assemble_chunks_for_db,
    get_settings,
    pg_service,
    logger,
) -> Dict[str, Any]:
    logger.info("[Ingest] Starting file processing: %s", filename)

    ingestion_steps.validate_supported_upload(filename, mimetype, is_supported_upload)

    file_hash = ingestion_steps.content_hash(content)
    existing = pg_service.find_document_by_hash(file_hash, class_id, user_id=user_id)
    if existing:
        logger.info("[Ingest] Duplicate file detected: %s", filename)
        return ingestion_steps.duplicate_file_result(existing)

    if is_image_upload(filename, mimetype):
        chunks = ingestion_steps.build_image_chunks(filename, content, mimetype)
    else:
        pages_text = await ingestion_steps.extract_pdf_pages(content, extract_pdf_content_by_page)
        chunks = ingestion_steps.build_pdf_chunks(filename, pages_text, text_splitter)
    logger.info("[Ingest] Document split into %s chunks", len(chunks))

    primary_vectors, fallback_vectors = await ingestion_steps.embed_document_chunks(chunks, embed_chunks_for_storage)

    chunks_for_db = ingestion_steps.build_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        assemble_chunks_for_db=assemble_chunks_for_db,
        get_settings=get_settings,
    )

    try:
        result = ingestion_steps.build_and_store_document(
            name=filename,
            size=size,
            file_hash=file_hash,
            mimetype=mimetype or "application/pdf",
            class_id=class_id,
            user_id=user_id,
            chunks_for_db=chunks_for_db,
            pg_service=pg_service,
        )
    except Exception as err:
        stage = getattr(err, "stage", "unknown")
        embedding_columns = sorted(
            {
                column_name
                for chunk in chunks_for_db
                for column_name in ("embedding", "embedding_v2")
                if column_name in chunk
            }
        )
        logger.error(
            "[Ingest] Database storage failed filename=%s class_id=%s chunks=%s embedding_columns=%s "
            "storage_stage=%s error_type=%s",
            filename,
            class_id,
            len(chunks_for_db),
            embedding_columns,
            stage,
            type(err).__name__,
            exc_info=True,
        )
        raise DocumentIngestError(
            code="INGEST_FAILED",
            message="Failed to store the document in the database.",
            details=f"storage_stage={stage}",
        ) from err

    if not result.get("isNew", True):
        logger.info("[Ingest] Duplicate file detected during document insert: %s", filename)
        return ingestion_steps.duplicate_file_result({"id": result["fileId"]})

    logger.info("[Ingest] File processing completed successfully: %s", filename)
    return ingestion_steps.build_uploaded_result(filename, result["fileId"], len(chunks))


async def ingest_website(
    *,
    url: str,
    client_id: Optional[str],
    class_id: Optional[str],
    user_id: Optional[str],
    load_markdown,
    text_splitter,
    embed_chunks_for_storage,
    assemble_chunks_for_db,
    get_settings,
    pg_service,
    publish_progress,
    logger,
) -> Dict[str, Any]:
    logger.info("[Ingest] Starting website processing: %s", url)

    markdown = document_sources.markdown_documents_to_text(await load_markdown(url))
    file_hash, size = ingestion_steps.markdown_hash_and_size(markdown)
    existing = pg_service.find_document_by_hash(file_hash, class_id, user_id=user_id)
    if existing:
        logger.info("[Ingest] Duplicate website detected: %s", url)
        return ingestion_steps.duplicate_website_result(existing)

    chunks = ingestion_steps.split_website_chunks(markdown, url, text_splitter)
    total_tasks = len(chunks)
    total_with_db = total_tasks + 1
    await ingestion_steps.publish_progress_event(publish_progress, client_id, 0, total_with_db)

    primary_vectors, fallback_vectors = await embed_chunks_for_storage(chunks)
    chunks_for_db = ingestion_steps.build_chunks_for_db(
        chunks,
        primary_vectors,
        fallback_vectors,
        assemble_chunks_for_db=assemble_chunks_for_db,
        get_settings=get_settings,
    )
    result = ingestion_steps.build_and_store_document(
        name=url,
        size=size,
        file_hash=file_hash,
        mimetype="text/markdown",
        class_id=class_id,
        user_id=user_id,
        chunks_for_db=chunks_for_db,
        pg_service=pg_service,
    )

    if not result.get("isNew", True):
        logger.info("[Ingest] Duplicate website detected during document insert: %s", url)
        return ingestion_steps.duplicate_website_result({"id": result["fileId"]})

    await ingestion_steps.publish_progress_event(publish_progress, client_id, total_with_db, total_with_db)
    await ingestion_steps.publish_finished_event(publish_progress, client_id, result["fileId"], len(chunks))
    return ingestion_steps.build_uploaded_result(url, result["fileId"], len(chunks))
