from __future__ import annotations

import json
from typing import AsyncGenerator, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.routers.service_helpers import error_detail
from app.services import adaptive_rag_service

router = APIRouter(prefix="", tags=["query"])

_reciprocal_rank_fusion = adaptive_rag_service._reciprocal_rank_fusion
_retrieve_vector_context = adaptive_rag_service._retrieve_vector_context


class QueryStreamRequest(BaseModel):
    question: str
    selectedFileIds: List[str] = Field(default_factory=list)


def _encode_sse_event(payload: dict) -> bytes:
    event_name = payload.get("type") or "message"
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {data}\n\n".encode("utf-8")


async def sse_event_stream(
    question: str,
    selected_file_ids: List[str],
) -> AsyncGenerator[bytes, None]:
    async for event in adaptive_rag_service.run_adaptive_rag_stream(
        question,
        selected_file_ids,
    ):
        yield _encode_sse_event(event)


@router.post("/query-stream")
async def query_stream(body: QueryStreamRequest):
    question = body.question.strip()
    if not question:
        raise HTTPException(
            status_code=400,
            detail=error_detail("Please provide a query question"),
        )
    if not body.selectedFileIds:
        raise HTTPException(
            status_code=400,
            detail=error_detail("Please select at least one document for retrieval"),
        )

    return StreamingResponse(
        sse_event_stream(question, body.selectedFileIds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
