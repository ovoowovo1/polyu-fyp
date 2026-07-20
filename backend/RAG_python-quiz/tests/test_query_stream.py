import unittest
from unittest.mock import patch

from app.routers import query_stream
from app.services.pg.rls_context import get_current_rls_user
from tests.support import build_authed_client


class QueryStreamRouteTests(unittest.TestCase):
    def setUp(self):
        self.app, self.client = build_authed_client(
            query_stream.router,
            query_stream.get_current_user,
            {"user_id": "user-1", "email": "u@example.com"},
        )

    def post_query_stream(self, payload):
        return self.client.post("/query-stream", json=payload)

    def test_query_stream_requires_authentication(self):
        self.app.dependency_overrides.clear()
        response = self.post_query_stream({"question": "hello", "selectedFileIds": ["file-1"]})
        self.assertEqual(response.status_code, 401)

    def test_query_stream_route_validates_payload(self):
        cases = (
            ({"question": "   ", "selectedFileIds": ["file-1"]}, "Please provide a query question"),
            ({"question": "hello", "selectedFileIds": []}, "Please select at least one document for retrieval"),
        )
        for payload, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                response = self.post_query_stream(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["error"], expected_error)

    def test_query_stream_route_returns_streaming_response(self):
        async def fake_stream(question, selected_file_ids):
            self.assertEqual(get_current_rls_user(), "user-1")
            yield {"type": "retrieval", "message": "Starting retrieval...", "timestamp": "2026-01-01T00:00:00Z"}
            yield {"type": "result", "question": question, "answer": "ok", "timestamp": "2026-01-01T00:00:01Z"}

        with patch(
            "app.routers.query_stream.run_adaptive_rag_stream",
            fake_stream,
        ):
            response = self.post_query_stream({"question": "hello", "selectedFileIds": ["file-1"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        self.assertIn("event: retrieval", response.text)
        self.assertIn("event: result", response.text)
        self.assertIn('"answer": "ok"', response.text)

    def test_encode_sse_event_formats_event_and_data_lines(self):
        payload = {"type": "grader", "message": "checking", "timestamp": "2026-01-01T00:00:00Z"}

        encoded = query_stream._encode_sse_event(payload).decode("utf-8")

        self.assertEqual(
            encoded,
            'event: grader\ndata: {"type": "grader", "message": "checking", "timestamp": "2026-01-01T00:00:00Z"}\n\n',
        )
