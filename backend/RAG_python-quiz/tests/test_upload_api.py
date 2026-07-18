from unittest.mock import AsyncMock, patch
import unittest

from app.api_helpers import upload_helpers
from app.routers import upload
from app.routers.upload import router
from app.services.core.exceptions import PermissionDeniedError
from app.utils.ingest_errors import DocumentIngestError
from tests.support import build_authed_client, make_embedding_error


def make_success(file_id="file-1", *, is_new=True, chunks=3):
    return {
        "message": "Uploaded file",
        "fileId": file_id,
        "isNew": is_new,
        "chunksCount": chunks,
    }


class UploadApiTests(unittest.TestCase):
    def setUp(self):
        self.app, self.client = build_authed_client(
            router,
            upload.get_current_user,
            {"user_id": "user-1", "email": "u@example.com"},
        )

    def upload_multiple(self, side_effect):
        mock_ingest = AsyncMock(side_effect=side_effect)
        mock_progress = AsyncMock()
        files = [
            ("files", ("a.pdf", b"one", "application/pdf")),
            ("files", ("b.pdf", b"two", "application/pdf")),
        ]
        with patch("app.routers.upload.ingest_document", mock_ingest), patch(
            "app.routers.upload.publish_progress",
            mock_progress,
        ), patch(
            "app.routers.upload.require_class_teacher",
        ):
            response = self.client.post("/upload-multiple?class_id=class-1", files=files)

        return response, response.json(), mock_progress.await_args_list[-1].args[1]

    def test_upload_routes_require_authentication(self):
        self.app.dependency_overrides.clear()
        response = self.client.post("/upload-multiple")
        self.assertEqual(response.status_code, 401)

    def test_upload_multiple_returns_200_for_all_success_including_duplicates(self):
        with patch("app.routers.upload.redis_cache.invalidate_namespaces") as invalidate:
            response, payload, finished_event = self.upload_multiple(
                [
                    make_success("file-1", is_new=True, chunks=4),
                    make_success("file-1", is_new=False, chunks=0),
                ]
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 2, "failed": 0})
        self.assertFalse(payload["results"][1]["isNew"])
        self.assertEqual(payload["data"]["status"], "success")
        self.assertEqual(finished_event["type"], "finished")
        self.assertEqual(finished_event["status"], "success")
        invalidate.assert_called_with("files:list", "rag:retrieval", "files:detail:file-1")

    def test_upload_multiple_accepts_image_multipart_files(self):
        mock_ingest = AsyncMock(return_value=make_success("image-1", chunks=1))
        files = [("files", ("figure.png", b"image-bytes", "image/png"))]
        with patch("app.routers.upload.ingest_document", mock_ingest), patch(
            "app.routers.upload.publish_progress",
            AsyncMock(),
        ), patch(
            "app.routers.upload.require_class_teacher",
        ) as require_class_teacher, patch("app.routers.upload.redis_cache.invalidate_namespaces"):
            response = self.client.post("/upload-multiple?class_id=class-1", files=files)

        self.assertEqual(response.status_code, 200)
        require_class_teacher.assert_called_once_with("user-1", "class-1")
        self.assertEqual(response.json()["results"][0]["filename"], "figure.png")
        self.assertEqual(mock_ingest.await_args.kwargs["mimetype"], "image/png")
        self.assertEqual(mock_ingest.await_args.kwargs["content"], b"image-bytes")
        self.assertEqual(mock_ingest.await_args.kwargs["user_id"], "user-1")

    def test_upload_multiple_returns_207_for_partial_success(self):
        with patch("app.routers.upload.redis_cache.invalidate_namespaces") as invalidate:
            response, payload, finished_event = self.upload_multiple([make_success("file-1"), make_embedding_error()])

        self.assertEqual(response.status_code, 207)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 1, "failed": 1})
        self.assertEqual(payload["results"][1]["error"]["code"], "EMBEDDING_UPSTREAM_FAILED")
        self.assertEqual(finished_event["status"], "partial")
        invalidate.assert_called_with("files:list", "rag:retrieval", "files:detail:file-1")

    def test_upload_multiple_returns_502_when_all_files_fail(self):
        with patch("app.routers.upload.redis_cache.invalidate_namespaces") as invalidate:
            response, payload, finished_event = self.upload_multiple(
                [
                    make_embedding_error(),
                    DocumentIngestError(code="EMPTY_DOCUMENT", message="No extractable text was found in this PDF."),
                ]
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["summary"], {"total": 2, "succeeded": 0, "failed": 2})
        self.assertEqual(payload["results"][0]["error"]["code"], "EMBEDDING_UPSTREAM_FAILED")
        self.assertEqual(payload["results"][1]["error"]["code"], "EMPTY_DOCUMENT")
        self.assertEqual(finished_event["status"], "failed")
        invalidate.assert_called_with("files:list", "rag:retrieval")

    def test_upload_helper_functions_cover_unexpected_errors(self):
        result = upload_helpers.build_failure_result("broken.pdf", RuntimeError("boom"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "INGEST_FAILED")
        self.assertEqual(upload._unique_string_ids([None, "", "file-1", "file-1", 2]), ["file-1", "2"])

    def test_upload_multiple_rejects_missing_files(self):
        response = self.client.post("/upload-multiple")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Please provide at least one file.")

    def test_upload_routes_reject_non_owner_before_ingestion(self):
        files = [("files", ("a.pdf", b"one", "application/pdf"))]
        with patch(
            "app.routers.upload.require_class_teacher",
            side_effect=PermissionDeniedError("Permission denied"),
        ), patch("app.routers.upload.ingest_document", AsyncMock()) as ingest_document:
            response = self.client.post("/upload-multiple?class_id=class-1", files=files)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], {
            "error": upload.UPLOAD_FORBIDDEN_MESSAGE,
            "code": "UPLOAD_FORBIDDEN",
        })
        ingest_document.assert_not_awaited()

        with patch(
            "app.routers.upload.require_class_teacher",
            side_effect=PermissionDeniedError("Permission denied"),
        ), patch("app.routers.upload.ingest_website", AsyncMock()) as ingest_website:
            response = self.client.post(
                "/upload-link?class_id=class-1",
                json={"url": "https://example.com"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "UPLOAD_FORBIDDEN")
        ingest_website.assert_not_awaited()

    def test_upload_routes_require_a_class_id(self):
        files = [("files", ("a.pdf", b"one", "application/pdf"))]
        response = self.client.post("/upload-multiple", files=files)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "class_id is required for document uploads.")

        response = self.client.post("/upload-link", json={"url": "https://example.com"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "class_id is required for document uploads.")

    def test_upload_link_success_and_error_paths(self):
        with patch("app.routers.upload.ingest_website", AsyncMock(return_value={"fileId": "site-1"})), patch(
            "app.routers.upload.require_class_teacher",
        ), patch(
            "app.routers.upload.redis_cache.invalidate_namespaces"
        ) as invalidate:
            response = self.client.post("/upload-link?class_id=class-1", json={"url": " https://example.com "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["fileId"], "site-1")
        self.assertEqual(response.json()["data"]["fileId"], "site-1")
        invalidate.assert_called_with("files:list", "rag:retrieval", "files:detail:site-1")

        missing = self.client.post("/upload-link", json={"url": "   "})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["error"], "url is required")

        with patch("app.routers.upload.ingest_website", AsyncMock(side_effect=RuntimeError("crawl failed"))), patch(
            "app.routers.upload.require_class_teacher",
        ):
            failed = self.client.post("/upload-link?class_id=class-1", json={"url": "https://example.com"})
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"], "Failed to upload link.")
