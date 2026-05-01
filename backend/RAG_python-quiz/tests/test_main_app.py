import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main


class MainAppTests(unittest.TestCase):
    def build_logged_client(self, *, raise_server_exceptions=True):
        app = FastAPI()
        main._add_request_logging_middleware(app)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.get("/boom")
        def boom():
            raise RuntimeError("boom")

        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    def test_default_static_dir_points_to_backend_static_folder(self):
        static_dir = Path(main._default_static_dir()).resolve()
        self.assertEqual(static_dir.parts[-3:], ("backend", "RAG_python-quiz", "static"))

    def test_create_startup_handler_calls_vector_index_setup(self):
        with patch("main.pg_service.setup_vector_index") as setup_vector_index:
            handler = main._create_startup_handler()
            handler()

        setup_vector_index.assert_called_once_with()

    def test_create_app_mounts_static_and_registers_startup_event(self):
        settings = SimpleNamespace(cors_origins=["http://localhost:5173"], port=3000)
        with tempfile.TemporaryDirectory() as tmpdir:
            app = main.create_app(settings=settings, static_dir=tmpdir)

        routes = {route.path for route in app.routes}
        self.assertIn("/files", routes)
        self.assertNotIn("/neo4j/files", routes)
        self.assertIn("/api/query-stream", routes)
        self.assertNotIn("/query-stream", routes)
        self.assertIn("/static", routes)
        self.assertTrue(any(handler.__name__ == "on_startup" for handler in app.router.on_startup))

    def test_main_entrypoint_runs_uvicorn_with_expected_host_and_port(self):
        settings = SimpleNamespace(cors_origins=["*"], port=4321)
        module_path = Path(main.__file__)

        with patch("app.config.get_settings", return_value=settings), patch("uvicorn.run") as uvicorn_run:
            runpy.run_path(str(module_path), run_name="__main__")

        uvicorn_run.assert_called_once_with("main:app", host="0.0.0.0", port=4321, reload=True)

    def test_request_logging_records_anonymous_without_authorization_header(self):
        client = self.build_logged_client()

        with self.assertLogs("api.request", level="INFO") as logs:
            response = client.get("/ok", headers={"user-agent": "test-agent"})

        self.assertEqual(response.status_code, 200)
        message = logs.output[0]
        self.assertIn("user_id=anonymous", message)
        self.assertIn("email=anonymous", message)
        self.assertIn("method=GET", message)
        self.assertIn("path=/ok", message)
        self.assertIn("status_code=200", message)
        self.assertIn("user_agent=test-agent", message)

    def test_request_logging_records_user_from_bearer_token(self):
        client = self.build_logged_client()
        payload = {"sub": "user-1", "username": "student@example.com"}

        with patch("main.verify_token", return_value=payload) as verify_token:
            with self.assertLogs("api.request", level="INFO") as logs:
                response = client.get("/ok", headers={"Authorization": "Bearer good-token"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_called_once_with("good-token")
        message = logs.output[0]
        self.assertIn("user_id=user-1", message)
        self.assertIn("email=student@example.com", message)
        self.assertNotIn("good-token", message)

    def test_request_logging_uses_anonymous_for_invalid_token(self):
        client = self.build_logged_client()

        with patch("main.verify_token", return_value=None) as verify_token:
            with self.assertLogs("api.request", level="INFO") as logs:
                response = client.get("/ok", headers={"Authorization": "Bearer bad-token"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_called_once_with("bad-token")
        message = logs.output[0]
        self.assertIn("user_id=anonymous", message)
        self.assertIn("email=anonymous", message)
        self.assertNotIn("bad-token", message)

    def test_request_logging_uses_anonymous_for_malformed_authorization_header(self):
        client = self.build_logged_client()

        with patch("main.verify_token") as verify_token:
            with self.assertLogs("api.request", level="INFO") as logs:
                response = client.get("/ok", headers={"Authorization": "Basic abc"})

        self.assertEqual(response.status_code, 200)
        verify_token.assert_not_called()
        self.assertIn("user_id=anonymous", logs.output[0])

    def test_request_logging_uses_anonymous_for_token_without_subject(self):
        client = self.build_logged_client()

        with patch("main.verify_token", return_value={"username": "student@example.com"}):
            with self.assertLogs("api.request", level="INFO") as logs:
                response = client.get("/ok", headers={"Authorization": "Bearer no-sub-token"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("user_id=anonymous", logs.output[0])
        self.assertIn("email=anonymous", logs.output[0])

    def test_request_logging_prefers_forwarded_client_ip(self):
        client = self.build_logged_client()

        with self.assertLogs("api.request", level="INFO") as logs:
            response = client.get("/ok", headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("client_ip=203.0.113.7", logs.output[0])

    def test_request_logging_records_exception_and_preserves_error_response(self):
        client = self.build_logged_client(raise_server_exceptions=False)

        with self.assertLogs("api.request", level="ERROR") as logs:
            response = client.get("/boom")

        self.assertEqual(response.status_code, 500)
        message = logs.output[0]
        self.assertIn("user_id=anonymous", message)
        self.assertIn("method=GET", message)
        self.assertIn("path=/boom", message)
        self.assertIn("status_code=error", message)
