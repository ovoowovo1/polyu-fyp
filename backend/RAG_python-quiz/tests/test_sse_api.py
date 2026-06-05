import asyncio
import unittest
from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers import sse


class _FakeRequest:
    def __init__(self, disconnect_sequence):
        self._disconnect_sequence = iter(disconnect_sequence)

    async def is_disconnected(self):
        return next(self._disconnect_sequence)


async def progress_chunks(*, queued_event=None, wait_for=None):
    queue = asyncio.Queue()
    if queued_event is not None:
        await queue.put(queued_event)
    remove_queue = AsyncMock()
    wait_for_patch = patch("app.routers.sse.asyncio.wait_for", side_effect=wait_for) if wait_for else nullcontext()

    with patch("app.routers.sse.get_queue", AsyncMock(return_value=queue)), patch(
        "app.routers.sse.remove_queue",
        remove_queue,
    ), wait_for_patch:
        response = await sse.sse_progress(_FakeRequest([False, True]), "client-1")
        chunks = [chunk async for chunk in response.body_iterator]

    remove_queue.assert_awaited_once_with("client-1")
    return chunks


class SseApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_requires_client_id(self):
        with self.assertRaises(HTTPException) as ctx:
            await sse.sse_progress(_FakeRequest([False]), "")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "clientId is required")

    async def test_progress_streams_queue_data_and_cleans_up(self):
        chunks = await progress_chunks(queued_event={"type": "progress", "step": 1})

        self.assertEqual(len(chunks), 1)
        self.assertIn('"type": "progress"', chunks[0])

    async def test_progress_sends_keepalive_on_timeout(self):
        async def fake_wait_for(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        chunks = await progress_chunks(wait_for=fake_wait_for)

        self.assertEqual(chunks, ['data: {"type": "keepalive"}\n\n'])
