import unittest
from unittest.mock import patch

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

    def test_delete_file_success(self):
        response = self.route(
            "delete",
            "/files/file-1",
            "delete_file_record",
            return_value={"message": "Deleted", "deletedFile": {"id": "file-1"}},
        )
        self.assertTrue(response.json()["success"])

    def test_get_file_details_success(self):
        response = self.route(
            "get",
            "/files/file-1",
            "get_specific_file",
            return_value={"file": {"id": "file-1"}, "chunks": [{"id": "chunk-1"}]},
        )
        self.assertEqual(response.json()["file"]["id"], "file-1")

    def test_rename_file_success(self):
        response = self.route(
            "put",
            "/files/file-1",
            "rename_file_record",
            return_value={"message": "Renamed", "renamedFile": {"id": "file-1", "name": "new.pdf"}},
            params={"new_name": "new.pdf"},
        )
        self.assertEqual(response.json()["renamedFile"]["name"], "new.pdf")

    def test_get_chunk_source_details_success(self):
        response = self.route(
            "get", "/chunks/chunk-1/source-details", "get_source_details_by_chunk_id", return_value={"page": 2}
        )
        self.assertEqual(response.json()["details"]["page"], 2)

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

