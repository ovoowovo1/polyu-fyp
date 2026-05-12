from __future__ import annotations

import json
from typing import AsyncGenerator, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.routers.service_helpers import error_detail
from app.services.pg.rls_context import clear_current_rls_user, set_current_rls_user
from app.services.rag import adaptive_rag_service
from app.utils.jwt_utils import get_current_user

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
    user_id: str,
) -> AsyncGenerator[bytes, None]:
    set_current_rls_user(user_id)
    try:
        async for event in adaptive_rag_service.run_adaptive_rag_stream(
            question,
            selected_file_ids,
        ):
            yield _encode_sse_event(event)
    finally:
        clear_current_rls_user()


@router.post("/query-stream")
async def query_stream(body: QueryStreamRequest, user: dict = Depends(get_current_user)):
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
        sse_event_stream(question, body.selectedFileIds, user["user_id"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
