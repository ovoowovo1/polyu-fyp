import unittest
from unittest.mock import patch

from app.routers import files_pg
from app.services.exceptions import NotFoundError
from tests.support import build_client


class FilesPgApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(files_pg.router)

    def test_get_files_success(self):
        with patch("app.routers.files_pg.pg_service.get_files_list", return_value=[{"id": "file-1"}]):
            response = self.client.get("/files", params={"class_id": "class-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    def test_get_files_failure(self):
        with patch("app.routers.files_pg.pg_service.get_files_list", side_effect=Exception("db")):
            response = self.client.get("/files")

        self.assertEqual(response.status_code, 500)

    def test_delete_file_success(self):
        with patch(
            "app.routers.files_pg.pg_service.delete_file",
            return_value={"message": "Deleted", "deletedFile": {"id": "file-1"}},
        ):
            response = self.client.delete("/files/file-1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_delete_file_not_found(self):
        with patch("app.routers.files_pg.pg_service.delete_file", side_effect=NotFoundError("File not found")):
            response = self.client.delete("/files/file-1")

        self.assertEqual(response.status_code, 404)

    def test_delete_file_server_error(self):
        with patch("app.routers.files_pg.pg_service.delete_file", side_effect=Exception("boom")):
            response = self.client.delete("/files/file-1")

        self.assertEqual(response.status_code, 500)

    def test_get_file_details_success(self):
        with patch(
            "app.routers.files_pg.pg_service.get_specific_file",
            return_value={"file": {"id": "file-1"}, "chunks": [{"id": "chunk-1"}]},
        ):
            response = self.client.get("/files/file-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["file"]["id"], "file-1")

    def test_get_file_details_not_found(self):
        with patch("app.routers.files_pg.pg_service.get_specific_file", side_effect=NotFoundError("File not found")):
            response = self.client.get("/files/file-1")

        self.assertEqual(response.status_code, 404)

    def test_get_file_details_server_error(self):
        with patch("app.routers.files_pg.pg_service.get_specific_file", side_effect=Exception("boom")):
            response = self.client.get("/files/file-1")

        self.assertEqual(response.status_code, 500)

    def test_rename_file_success(self):
        with patch(
            "app.routers.files_pg.pg_service.rename_file",
            return_value={"message": "Renamed", "renamedFile": {"id": "file-1", "name": "new.pdf"}},
        ):
            response = self.client.put("/files/file-1", params={"new_name": "new.pdf"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["renamedFile"]["name"], "new.pdf")

    def test_rename_file_server_error(self):
        with patch("app.routers.files_pg.pg_service.rename_file", side_effect=Exception("boom")):
            response = self.client.put("/files/file-1", params={"new_name": "new.pdf"})

        self.assertEqual(response.status_code, 500)

    def test_get_chunk_source_details_success(self):
        with patch("app.routers.files_pg.pg_service.get_source_details_by_chunk_id", return_value={"page": 2}):
            response = self.client.get("/chunks/chunk-1/source-details")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["details"]["page"], 2)

    def test_get_chunk_source_details_not_found(self):
        with patch("app.routers.files_pg.pg_service.get_source_details_by_chunk_id", side_effect=NotFoundError("Chunk not found")):
            response = self.client.get("/chunks/chunk-1/source-details")

        self.assertEqual(response.status_code, 404)

    def test_get_chunk_source_details_server_error(self):
        with patch("app.routers.files_pg.pg_service.get_source_details_by_chunk_id", side_effect=Exception("boom")):
            response = self.client.get("/chunks/chunk-1/source-details")

        self.assertEqual(response.status_code, 500)
