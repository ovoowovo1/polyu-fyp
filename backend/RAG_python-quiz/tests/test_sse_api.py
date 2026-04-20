import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers import sse


class _FakeRequest:
    def __init__(self, disconnect_sequence):
        self._disconnect_sequence = iter(disconnect_sequence)

    async def is_disconnected(self):
        return next(self._disconnect_sequence)


class SseApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_requires_client_id(self):
        with self.assertRaises(HTTPException) as ctx:
            await sse.sse_progress(_FakeRequest([False]), "")

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_progress_streams_queue_data_and_cleans_up(self):
        queue = asyncio.Queue()
        await queue.put({"type": "progress", "step": 1})
        remove_queue = AsyncMock()

        with patch("app.routers.sse.get_queue", AsyncMock(return_value=queue)), patch(
            "app.routers.sse.remove_queue",
            remove_queue,
        ):
            response = await sse.sse_progress(_FakeRequest([False, True]), "client-1")
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertEqual(len(chunks), 1)
        self.assertIn('"type": "progress"', chunks[0])
        remove_queue.assert_awaited_once_with("client-1")

    async def test_progress_sends_keepalive_on_timeout(self):
        queue = asyncio.Queue()
        remove_queue = AsyncMock()

        async def fake_wait_for(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        with patch("app.routers.sse.get_queue", AsyncMock(return_value=queue)), patch(
            "app.routers.sse.remove_queue",
            remove_queue,
        ), patch(
            "app.routers.sse.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            response = await sse.sse_progress(_FakeRequest([False, True]), "client-1")
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertEqual(chunks, ['data: {"type": "keepalive"}\n\n'])
        remove_queue.assert_awaited_once_with("client-1")
