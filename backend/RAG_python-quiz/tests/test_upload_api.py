from unittest.mock import AsyncMock, patch
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import upload
from app.routers.upload import router
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError


def make_success(file_id="file-1", *, is_new=True, chunks=3):
    return {
        "message": "Uploaded file",
        "fileId": file_id,
        "isNew": is_new,
        "chunksCount": chunks,
    }


def make_embedding_error():
    return EmbeddingProviderError(
        code="EMBEDDING_UPSTREAM_FAILED",
        message="Embedding upstream failed: No successful provider responses.",
        retryable=True,
        provider="openrouter",
        model="google/gemini-embedding-001",
        base_url="https://openrouter.ai/api/v1",
        http_status=200,
        upstream_code=404,
        upstream_message="No successful provider responses.",
        raw_preview='{"error":{"message":"No successful provider responses.","code":404}}',
    )


class UploadApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_upload_multiple_returns_200_for_all_success_including_duplicates(self):
        mock_ingest = AsyncMock(
            side_effect=[
                make_success("file-1", is_new=True, chunks=4),
                make_success("file-1", is_new=False, chunks=0),
            ]
        )
        mock_progress = AsyncMock()

        with patch("app.routers.upload.ingest_document", mock_ingest), patch(
            "app.routers.upload.publish_progress",
            mock_progress,
        ):
            response = self.client.post(
                "/upload-multiple",
                files=[
                    ("files", ("a.pdf", b"one", "application/pdf")),
                    ("files", ("b.pdf", b"two", "application/pdf")),
                ],
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 2, "failed": 0})
        self.assertFalse(payload["results"][1]["isNew"])
        self.assertEqual(payload["data"]["status"], "success")
        finished_event = mock_progress.await_args_list[-1].args[1]
        self.assertEqual(finished_event["type"], "finished")
        self.assertEqual(finished_event["status"], "success")

    def test_upload_multiple_returns_207_for_partial_success(self):
        mock_ingest = AsyncMock(side_effect=[make_success("file-1"), make_embedding_error()])
        mock_progress = AsyncMock()

        with patch("app.routers.upload.ingest_document", mock_ingest), patch(
            "app.routers.upload.publish_progress",
            mock_progress,
        ):
            response = self.client.post(
                "/upload-multiple",
                files=[
                    ("files", ("a.pdf", b"one", "application/pdf")),
                    ("files", ("b.pdf", b"two", "application/pdf")),
                ],
            )

        self.assertEqual(response.status_code, 207)
        payload = response.json()
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 1, "failed": 1})
        self.assertEqual(payload["results"][1]["error"]["code"], "EMBEDDING_UPSTREAM_FAILED")
        finished_event = mock_progress.await_args_list[-1].args[1]
        self.assertEqual(finished_event["status"], "partial")

    def test_upload_multiple_returns_502_when_all_files_fail(self):
        mock_ingest = AsyncMock(
            side_effect=[
                make_embedding_error(),
                DocumentIngestError(code="EMPTY_DOCUMENT", message="No extractable text was found in this PDF."),
            ]
        )
        mock_progress = AsyncMock()

        with patch("app.routers.upload.ingest_document", mock_ingest), patch(
            "app.routers.upload.publish_progress",
            mock_progress,
        ):
            response = self.client.post(
                "/upload-multiple",
                files=[
                    ("files", ("a.pdf", b"one", "application/pdf")),
                    ("files", ("b.pdf", b"two", "application/pdf")),
                ],
            )

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 0, "failed": 2})
        self.assertEqual(payload["results"][0]["error"]["code"], "EMBEDDING_UPSTREAM_FAILED")
        self.assertEqual(payload["results"][1]["error"]["code"], "EMPTY_DOCUMENT")
        finished_event = mock_progress.await_args_list[-1].args[1]
        self.assertEqual(finished_event["status"], "failed")

    def test_upload_helper_functions_cover_unexpected_errors(self):
        result = upload._build_failure_result("broken.pdf", RuntimeError("boom"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "INGEST_FAILED")

    def test_upload_multiple_rejects_missing_files(self):
        response = self.client.post("/upload-multiple")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Please provide at least one file.")

    def test_upload_link_success_and_error_paths(self):
        with patch("app.routers.upload.ingest_website", AsyncMock(return_value={"fileId": "site-1"})):
            response = self.client.post("/upload-link", json={"url": " https://example.com "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["fileId"], "site-1")
        self.assertEqual(response.json()["data"]["fileId"], "site-1")

        missing = self.client.post("/upload-link", json={"url": "   "})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["error"], "url is required")

        with patch("app.routers.upload.ingest_website", AsyncMock(side_effect=RuntimeError("crawl failed"))):
            failed = self.client.post("/upload-link", json={"url": "https://example.com"})
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"], "Failed to upload link.")
