from datetime import datetime

from app.services import pg_service
from tests.pg_service_test_support import PgServiceBase
from tests.support import FakeCursor


class PgFilesServiceTests(PgServiceBase):
    module_path = "app.services.pg_files_service"

    def test_file_listing_and_mutations_cover_success_and_missing_rows(self):
        upload_time = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(
            fetchall_results=[
                [{"id": "file-1", "name": "lesson.pdf", "size": 10, "mime_type": "application/pdf", "upload_date": upload_time, "total_chunks": 2}],
                [{"id": "file-2", "name": "slides.pdf", "size": 20, "mime_type": "application/pdf", "upload_date": upload_time, "total_chunks": 1}],
            ]
        )
        with self.patch_conn(cursor):
            all_files = pg_service.get_files_list()
            class_files = pg_service.get_files_list("class-1")

        self.assertEqual(all_files[0]["total_chunks"], 2)
        self.assertEqual(class_files[0]["filename"], "slides.pdf")

        cursor = FakeCursor(fetchone_results=[{"id": "file-1", "name": "lesson.pdf"}])
        with self.patch_conn(cursor):
            deleted = pg_service.delete_file("file-1")
        self.assertEqual(deleted["deletedFile"]["id"], "file-1")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.delete_file("missing")

        cursor = FakeCursor(fetchone_results=[{"id": "file-1", "name": "renamed.pdf"}])
        with self.patch_conn(cursor):
            renamed = pg_service.rename_file("file-1", "renamed.pdf")
        self.assertEqual(renamed["renamedFile"]["name"], "renamed.pdf")

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.rename_file("missing", "name.pdf")

    def test_specific_file_and_source_detail_helpers_cover_missing_and_success(self):
        upload_time = datetime(2025, 1, 2, 3, 4, 5)
        cursor = FakeCursor(
            fetchone_results=[{"id": "file-1", "name": "lesson.pdf", "size_bytes": 10, "mimetype": "application/pdf", "created_at": upload_time}],
            fetchall_results=[[{"id": "chunk-1", "content": "chunk text", "chunk_index": 0}]],
        )
        with self.patch_conn(cursor):
            result = pg_service.get_specific_file("file-1")
        self.assertEqual(result["chunks"][0]["chunk_index"], 0)

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_specific_file("missing")

        cursor = FakeCursor(fetchone_results=[{"file_id": "file-1", "page_start": 3, "chunk_index": 1, "source_file": "lesson.pdf", "chunk_id": "chunk-1"}])
        with self.patch_conn(cursor):
            detail = pg_service.get_source_details_by_chunk_id("chunk-1")
        self.assertEqual(detail["page_number"], 3)

        with self.patch_conn(FakeCursor(fetchone_results=[None])):
            with self.assertRaises(RuntimeError):
                pg_service.get_source_details_by_chunk_id("missing")

    def test_get_files_text_content_validates_inputs_and_groups_content(self):
        with self.assertRaises(RuntimeError):
            pg_service.get_files_text_content([])

        with self.patch_conn(FakeCursor(fetchall_results=[[]])):
            with self.assertRaises(RuntimeError):
                pg_service.get_files_text_content(["file-1"])

        cursor = FakeCursor(
            fetchall_results=[
                [
                    {"file_name": "a.pdf", "text": "A1", "chunk_index": 0},
                    {"file_name": "a.pdf", "text": "A2", "chunk_index": 1},
                    {"file_name": "b.pdf", "text": "B1", "chunk_index": 0},
                ]
            ]
        )
        with self.patch_conn(cursor):
            content = pg_service.get_files_text_content(["file-1", "file-2"])
        self.assertIn("=== a.pdf ===", content)
        self.assertIn("B1", content)
