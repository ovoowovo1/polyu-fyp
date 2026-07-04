import unittest
from unittest.mock import AsyncMock, patch

from app.routers import files_pg
from app.services.core.exceptions import NotFoundError
from tests.support import build_authed_client, start_patches


class FilesPgApiTests(unittest.TestCase):
    def setUp(self):
        self.app, self.client = build_authed_client(
            files_pg.router,
            files_pg.get_current_user,
            {"user_id": "user-1", "email": "u@example.com"},
        )
        start_patches(
            self,
            patch("app.routers.files_pg.is_user_teacher", return_value=True),
            patch("app.routers.files_pg.can_access_class", return_value=True),
            patch("app.routers.files_pg.can_access_document", return_value=True),
            patch("app.routers.files_pg.can_access_chunk", return_value=True),
        )

    def route(self, method, path, service_name, *, status=200, return_value=None, side_effect=None, **kwargs):
        patch_kwargs = {"side_effect": side_effect} if side_effect is not None else {"return_value": return_value}
        with patch(f"app.routers.files_pg.{service_name}", **patch_kwargs):
            response = getattr(self.client, method)(path, **kwargs)

        self.assertEqual(response.status_code, status)
        return response

    def test_files_routes_require_authentication(self):
        self.app.dependency_overrides.clear()
        response = self.client.get("/files")
        self.assertEqual(response.status_code, 401)

    def test_get_files_success(self):
        response = self.route(
            "get", "/files", "get_files_list", return_value=[{"id": "file-1"}], params={"class_id": "class-1"}
        )
        self.assertEqual(response.json()["total"], 1)

    def test_get_files_uses_cache_after_class_access_check(self):
        with patch(
            "app.routers.files_pg.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=files_pg.redis_cache.CacheResult(
                    {"message": "Files fetched", "files": [{"id": "file-1"}], "total": 1},
                    "MISS",
                    "files:list",
                )
            ),
        ) as get_or_set, patch("app.routers.files_pg.get_files_list") as get_files_list:
            response = self.client.get("/files", params={"class_id": "class-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "MISS")
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(get_or_set.call_args.args[0], "files:list")
        get_files_list.assert_not_called()

    def test_delete_file_success(self):
        response = self.route(
            "delete",
            "/files/file-1",
            "delete_file_record",
            return_value={"message": "Deleted", "deletedFile": {"id": "file-1"}},
        )
        self.assertTrue(response.json()["success"])

    def test_delete_file_invalidates_file_cache(self):
        with patch(
            "app.routers.files_pg.delete_file_record",
            return_value={"message": "Deleted", "deletedFile": {"id": "file-1"}},
        ), patch("app.routers.files_pg.redis_cache.invalidate_namespaces") as invalidate:
            response = self.client.delete("/files/file-1")

        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_with("files:list", "files:detail:file-1", "chunks:source-details", "rag:retrieval")

    def test_get_file_details_success(self):
        response = self.route(
            "get",
            "/files/file-1",
            "get_specific_file",
            return_value={"file": {"id": "file-1"}, "chunks": [{"id": "chunk-1"}]},
        )
        self.assertEqual(response.json()["file"]["id"], "file-1")

    def test_get_file_details_uses_cache_when_enabled_and_access_probe_passes(self):
        with patch("app.routers.files_pg.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.files_pg.can_access_document",
            return_value=True,
        ), patch(
            "app.routers.files_pg.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=files_pg.redis_cache.CacheResult(
                    {"message": "File details fetched", "file": {"id": "file-1"}, "chunks": []},
                    "HIT",
                    "files:detail",
                )
            ),
        ) as get_or_set, patch("app.routers.files_pg.get_specific_file") as get_specific_file:
            response = self.client.get("/files/file-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "HIT")
        self.assertEqual(get_or_set.call_args.args[0], "files:detail")
        get_specific_file.assert_not_called()

    def test_get_file_details_skips_cache_when_access_probe_fails(self):
        with patch("app.routers.files_pg.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.files_pg.can_access_document",
            side_effect=[True, RuntimeError("access db")],
        ), patch(
            "app.routers.files_pg.get_specific_file",
            return_value={"file": {"id": "file-1"}, "chunks": []},
        ), patch("app.routers.files_pg.redis_cache.get_or_set_json_with_status", AsyncMock()) as get_or_set:
            response = self.client.get("/files/file-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "BYPASS")
        get_or_set.assert_not_called()

    def test_rename_file_success(self):
        response = self.route(
            "put",
            "/files/file-1",
            "rename_file_record",
            return_value={"message": "Renamed", "renamedFile": {"id": "file-1", "name": "new.pdf"}},
            params={"new_name": "new.pdf"},
        )
        self.assertEqual(response.json()["renamedFile"]["name"], "new.pdf")

    def test_rename_file_invalidates_file_cache(self):
        with patch(
            "app.routers.files_pg.rename_file_record",
            return_value={"message": "Renamed", "renamedFile": {"id": "file-1", "name": "new.pdf"}},
        ), patch("app.routers.files_pg.redis_cache.invalidate_namespaces") as invalidate:
            response = self.client.put("/files/file-1", params={"new_name": "new.pdf"})

        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_with("files:list", "files:detail:file-1", "chunks:source-details", "rag:retrieval")

    def test_get_chunk_source_details_success(self):
        response = self.route(
            "get", "/chunks/chunk-1/source-details", "get_source_details_by_chunk_id", return_value={"page": 2}
        )
        self.assertEqual(response.json()["details"]["page"], 2)

    def test_get_chunk_source_details_uses_cache_when_enabled_and_access_probe_passes(self):
        with patch("app.routers.files_pg.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.files_pg.can_access_chunk",
            return_value=True,
        ), patch(
            "app.routers.files_pg.redis_cache.get_or_set_json_with_status",
            AsyncMock(
                return_value=files_pg.redis_cache.CacheResult(
                    {"message": "Source details fetched", "details": {"page": 2}},
                    "HIT",
                    "chunks:source-details",
                )
            ),
        ) as get_or_set, patch("app.routers.files_pg.get_source_details_by_chunk_id") as source_details:
            response = self.client.get("/chunks/chunk-1/source-details")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "HIT")
        self.assertEqual(get_or_set.call_args.args[0], "chunks:source-details")
        source_details.assert_not_called()

    def test_get_chunk_source_details_skips_cache_when_access_probe_fails(self):
        with patch("app.routers.files_pg.redis_cache.is_enabled", return_value=True), patch(
            "app.routers.files_pg.can_access_chunk",
            side_effect=[True, RuntimeError("access db")],
        ), patch("app.routers.files_pg.get_source_details_by_chunk_id", return_value={"page": 2}), patch(
            "app.routers.files_pg.redis_cache.get_or_set_json_with_status",
            AsyncMock(),
        ) as get_or_set:
            response = self.client.get("/chunks/chunk-1/source-details")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Redis-Cache"], "BYPASS")
        get_or_set.assert_not_called()

    def test_file_routes_map_service_errors(self):
        cases = (
            ("get", "/files", "get_files_list", Exception("db"), 500, {}),
            ("delete", "/files/file-1", "delete_file_record", NotFoundError("File not found"), 404, {}),
            ("delete", "/files/file-1", "delete_file_record", Exception("boom"), 500, {}),
            ("get", "/files/file-1", "get_specific_file", NotFoundError("File not found"), 404, {}),
            ("get", "/files/file-1", "get_specific_file", Exception("boom"), 500, {}),
            ("put", "/files/file-1", "rename_file_record", Exception("boom"), 500, {"params": {"new_name": "new.pdf"}}),
            (
                "get",
                "/chunks/chunk-1/source-details",
                "get_source_details_by_chunk_id",
                NotFoundError("Chunk not found"),
                404,
                {},
            ),
            ("get", "/chunks/chunk-1/source-details", "get_source_details_by_chunk_id", Exception("boom"), 500, {}),
        )
        for method, path, service_name, error, status, kwargs in cases:
            with self.subTest(path=path, service_name=service_name, status=status):
                self.route(method, path, service_name, side_effect=error, status=status, **kwargs)

