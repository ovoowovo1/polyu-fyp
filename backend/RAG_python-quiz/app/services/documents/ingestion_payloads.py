from __future__ import annotations

from typing import Any, Dict, List, Optional


def assemble_chunks_for_db(
    chunks: List[Dict[str, Any]],
    primary_vectors: List[List[float]],
    fallback_vectors: Optional[List[List[float]]] = None,
    *,
    fallback_column: str = "embedding_v2",
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        payload = {
            "text": chunk["pageContent"],
            "metadata": chunk["metadata"],
            "embedding": primary_vectors[index],
        }
        if chunk.get("imageData") is not None:
            payload["image_data"] = chunk["imageData"]
            payload["image_mimetype"] = chunk.get("imageMimetype") or "image/png"
        if fallback_column != "embedding":
            payload[fallback_column] = fallback_vectors[index] if fallback_vectors is not None else None
        rows.append(payload)
    return rows


def build_document_data(
    *,
    name: str,
    size: int,
    file_hash: str,
    mimetype: str,
    class_id: Optional[str],
) -> Dict[str, Any]:
    document_data: Dict[str, Any] = {
        "name": name,
        "size": size,
        "hash": file_hash,
        "mimetype": mimetype,
    }
    if class_id:
        document_data["class_id"] = class_id
    return document_data
