import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import query_stream
from app.services.pg.rls_context import get_current_rls_user


class QueryStreamRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(query_stream.router)
        app.dependency_overrides[query_stream.get_current_user] = lambda: {
            "user_id": "user-1",
            "email": "u@example.com",
        }
        self.app = app
        self.client = TestClient(app)

    def test_query_stream_requires_authentication(self):
        self.app.dependency_overrides.clear()
        response = self.client.post("/query-stream", json={"question": "hello", "selectedFileIds": ["file-1"]})
        self.assertEqual(response.status_code, 401)

    def test_query_stream_route_validates_payload(self):
        missing_question = self.client.post("/query-stream", json={"question": "   ", "selectedFileIds": ["file-1"]})
        self.assertEqual(missing_question.status_code, 400)
        self.assertEqual(missing_question.json()["detail"]["error"], "Please provide a query question")

        missing_files = self.client.post("/query-stream", json={"question": "hello", "selectedFileIds": []})
        self.assertEqual(missing_files.status_code, 400)
        self.assertEqual(missing_files.json()["detail"]["error"], "Please select at least one document for retrieval")

    def test_query_stream_route_returns_streaming_response(self):
        async def fake_stream(question, selected_file_ids):
            self.assertEqual(get_current_rls_user(), "user-1")
            yield {"type": "retrieval", "message": "Starting retrieval...", "timestamp": "2026-01-01T00:00:00Z"}
            yield {"type": "result", "question": question, "answer": "ok", "timestamp": "2026-01-01T00:00:01Z"}

        with patch(
            "app.routers.query_stream.adaptive_rag_service.run_adaptive_rag_stream",
            fake_stream,
        ):
            response = self.client.post("/query-stream", json={"question": "hello", "selectedFileIds": ["file-1"]})

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
