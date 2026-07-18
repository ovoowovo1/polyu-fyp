import asyncio
import logging
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from app.logger import logger as logger_module
from app.services.documents import document_service
from app.services.pg import pg_db
from app.services.pg import rls_context
from app.services.realtime import progress_bus
from app.utils import datetime_utils, pdf_utils
from tests.support import FakeConnection, FakeCursor, make_settings


class RuntimeMiscTests(unittest.TestCase):
    def test_iso_handles_missing_and_present_datetime(self):
        cases = (
            (None, None),
            (datetime(2025, 1, 2, 3, 4, 5), "2025-01-02T03:04:05"),
        )

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(datetime_utils.iso(value), expected)

    def test_get_logger_reuses_existing_handlers(self):
        logger = logging.getLogger("tests.runtime.misc")
        logger.handlers.clear()
        try:
            configured = logger_module.get_logger("tests.runtime.misc")
            configured_again = logger_module.get_logger("tests.runtime.misc")
            self.assertIs(configured, configured_again)
            self.assertGreaterEqual(len(configured.handlers), 2)
        finally:
            logger.handlers.clear()

    def test_safe_rotating_file_handler_ignores_windows_sharing_violation(self):
        error = PermissionError("locked")
        error.winerror = logger_module.WINDOWS_SHARING_VIOLATION

        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = logger_module.SafeRotatingFileHandler(Path(tmp_dir) / "app.log")
            try:
                handler.stream.close()
                handler.stream = None
                with patch.object(logger_module.RotatingFileHandler, "doRollover", side_effect=error) as rollover:
                    handler.doRollover()

                rollover.assert_called_once()
                self.assertIsNotNone(handler.stream)
            finally:
                handler.close()

    def test_safe_rotating_file_handler_reraises_other_rollover_errors(self):
        error = PermissionError("locked")
        error.winerror = 5

        with tempfile.TemporaryDirectory() as tmp_dir:
            handler = logger_module.SafeRotatingFileHandler(Path(tmp_dir) / "app.log")
            try:
                with patch.object(logger_module.RotatingFileHandler, "doRollover", side_effect=error):
                    with self.assertRaises(PermissionError):
                        handler.doRollover()
            finally:
                handler.close()

    def test_pg_db_get_conn_uses_real_dict_cursor_and_settings(self):
        rls_context.clear_current_rls_user()
        settings = make_settings(pg_dsn="postgres://example")
        with patch("app.services.pg.pg_db.get_settings", return_value=settings), patch(
            "app.services.pg.pg_db.psycopg2.connect",
            return_value="connection",
        ) as connect:
            conn = pg_db._get_conn()

        self.assertEqual(conn, "connection")
        self.assertEqual(connect.call_args.args[0], "postgres://example")
        self.assertEqual(connect.call_args.kwargs["application_name"], "pg_service")

    def test_pg_db_get_conn_sets_transaction_local_rls_user_when_present(self):
        settings = make_settings(pg_dsn="postgres://example")
        cursor = FakeCursor()
        conn = FakeConnection(cursor)
        try:
            rls_context.set_current_rls_user("user-1")
            with patch("app.services.pg.pg_db.get_settings", return_value=settings), patch(
                "app.services.pg.pg_db.psycopg2.connect",
                return_value=conn,
            ):
                self.assertIs(pg_db._get_conn(), conn)
        finally:
            rls_context.clear_current_rls_user()

        self.assertEqual(
            cursor.executed,
            [("SELECT set_config('app.user_id', %s, true)", ("user-1",))],
        )

    def test_pg_db_get_conn_prefers_explicit_rls_user(self):
        settings = make_settings(pg_dsn="postgres://example")
        cursor = FakeCursor()
        conn = FakeConnection(cursor)
        try:
            rls_context.set_current_rls_user("context-user")
            with patch("app.services.pg.pg_db.get_settings", return_value=settings), patch(
                "app.services.pg.pg_db.psycopg2.connect",
                return_value=conn,
            ):
                self.assertIs(pg_db._get_conn("request-user"), conn)
        finally:
            rls_context.clear_current_rls_user()

        self.assertEqual(
            cursor.executed,
            [("SELECT set_config('app.user_id', %s, true)", ("request-user",))],
        )

    def test_pg_db_fetch_helpers_execute_and_return_rows(self):
        cursor = FakeCursor(
            fetchone_results=[{"id": "one"}],
            fetchall_results=[[{"id": "many"}]],
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            one = pg_db.fetch_one("SELECT one WHERE id=%s", ("one",))
            many = pg_db.fetch_all("SELECT many", None)

        self.assertEqual(one, {"id": "one"})
        self.assertEqual(many, [{"id": "many"}])
        self.assertEqual(cursor.executed[0], ("SELECT one WHERE id=%s", ("one",)))
        self.assertEqual(cursor.executed[1], ("SELECT many", None))
        self.assertFalse(conn.committed)

    def test_pg_db_write_helpers_commit_and_return_rows(self):
        cursor = FakeCursor(fetchone_results=[{"id": "updated"}])
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            row = pg_db.execute_returning("UPDATE x SET y=%s RETURNING id", ("y",))

        self.assertEqual(row, {"id": "updated"})
        self.assertTrue(conn.committed)
        self.assertEqual(cursor.executed[0], ("UPDATE x SET y=%s RETURNING id", ("y",)))

    def test_pg_db_with_cursor_write_controls_commit(self):
        read_conn = FakeConnection(FakeCursor())
        with patch("app.services.pg.pg_db._get_conn", return_value=read_conn):
            with pg_db.with_cursor() as cur:
                cur.execute("SELECT 1")
        self.assertFalse(read_conn.committed)

        write_conn = FakeConnection(FakeCursor())
        with patch("app.services.pg.pg_db._get_conn", return_value=write_conn):
            with pg_db.with_cursor(write=True) as cur:
                cur.execute("UPDATE x SET y=1")
        self.assertTrue(write_conn.committed)

    def test_pg_db_higher_level_helpers_reduce_row_boilerplate(self):
        cursor = FakeCursor(
            fetchone_results=[
                {"id": "required"},
                None,
                {"enabled": 1},
            ],
            fetchall_results=[[{"id": "a"}, {"id": "b"}]],
        )
        conn = FakeConnection(cursor)

        with patch("app.services.pg.pg_db._get_conn", return_value=conn):
            self.assertEqual(pg_db.require_row("SELECT required", error=ValueError("missing"))["id"], "required")
            with self.assertRaises(ValueError):
                pg_db.require_row("SELECT missing", error=ValueError("missing"))
            self.assertTrue(pg_db.fetch_bool("SELECT enabled", column="enabled"))
            self.assertEqual(pg_db.map_rows("SELECT rows", mapper=lambda row: row["id"].upper()), ["A", "B"])

        self.assertEqual(cursor.executed[0], ("SELECT required", None))
        self.assertEqual(cursor.executed[3], ("SELECT rows", None))

        direct_cursor = FakeCursor(fetchone_results=[{"id": "cursor-row"}, {"active": True}])
        self.assertEqual(pg_db.fetch_one_with_cursor(direct_cursor, "SELECT cursor")["id"], "cursor-row")
        self.assertTrue(pg_db.fetch_bool_with_cursor(direct_cursor, "SELECT active", column="active"))
        self.assertEqual(direct_cursor.executed, [("SELECT cursor", None), ("SELECT active", None)])

    def test_rls_context_tracks_and_clears_user(self):
        rls_context.set_current_rls_user("user-1")
        self.assertEqual(rls_context.get_current_rls_user(), "user-1")
        rls_context.clear_current_rls_user()
        self.assertIsNone(rls_context.get_current_rls_user())

    def test_load_markdown_transforms_async_html_documents(self):
        async def fake_aload():
            return ["<p>Hello</p>"]

        loader = SimpleNamespace(aload=fake_aload)
        transformer = SimpleNamespace(transform_documents=lambda docs: ["hello"])

        async def run():
            with patch("app.services.documents.document_service.AsyncHtmlLoader", return_value=loader), patch(
                "app.services.documents.document_service.MarkdownifyTransformer",
                return_value=transformer,
            ):
                return await document_service.load_markdown("https://example.com")

        self.assertEqual(asyncio.run(run()), ["hello"])

    def test_pdf_utils_extract_text_by_page_reads_each_page(self):
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buffer = BytesIO()
        writer.write(buffer)

        with patch("app.utils.pdf_utils.PdfReader") as reader_cls:
            fake_page = SimpleNamespace(extract_text=lambda: "page text")
            reader_cls.return_value.pages = [fake_page, SimpleNamespace(extract_text=lambda: None)]
            pages = asyncio.run(pdf_utils.extract_text_by_page(buffer.getvalue()))

        self.assertEqual(pages, ["page text", ""])

    def test_pdf_utils_extract_pdf_content_by_page_reads_embedded_images(self):
        image_file = SimpleNamespace(
            data=b"png-bytes",
            image=SimpleNamespace(format="PNG"),
            name="/Im0.png",
        )
        pages = [
            SimpleNamespace(
                extract_text=lambda: "page text",
                images=[image_file],
            ),
            SimpleNamespace(extract_text=lambda: None, images=[]),
        ]
        with patch("app.utils.pdf_utils.PdfReader") as reader_cls:
            reader_cls.return_value.pages = pages
            content = asyncio.run(pdf_utils.extract_pdf_content_by_page(b"pdf"))

        self.assertEqual(content[0]["pageNumber"], 1)
        self.assertEqual(content[0]["text"], "page text")
        self.assertEqual(content[0]["images"][0]["data"], b"png-bytes")
        self.assertEqual(content[0]["images"][0]["mimetype"], "image/png")
        self.assertEqual(content[0]["images"][0]["imageIndex"], 1)

    def test_pdf_utils_normalizes_unknown_image_format_and_rejects_empty_image(self):
        class FakeImage:
            format = None

            def save(self, output, format):
                self.saved_format = format
                output.write(b"normalized-png")

        data, mimetype = pdf_utils._extract_image_payload(
            SimpleNamespace(data=b"", image=FakeImage(), name="/Im0.bin")
        )
        self.assertEqual(data, b"normalized-png")
        self.assertEqual(mimetype, "image/png")

        with self.assertRaises(ValueError):
            pdf_utils._extract_image_payload(SimpleNamespace(data=b"", image=None, name="/Im0.bin"))


class ProgressBusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        progress_bus._queues.clear()

    async def test_get_queue_reuses_existing_queue(self):
        queue_a = await progress_bus.get_queue("client-1")
        queue_b = await progress_bus.get_queue("client-1")
        self.assertIs(queue_a, queue_b)

    async def test_remove_queue_discards_client_queue(self):
        await progress_bus.get_queue("client-1")
        await progress_bus.remove_queue("client-1")
        self.assertNotIn("client-1", progress_bus._queues)

    async def test_publish_progress_ignores_missing_client_or_queue(self):
        for client_id in (None, "client-1"):
            with self.subTest(client_id=client_id):
                await progress_bus.publish_progress(client_id, {"type": "noop"})
                self.assertEqual(progress_bus._queues, {})

    async def test_publish_progress_puts_event_on_queue(self):
        queue = await progress_bus.get_queue("client-1")
        await progress_bus.publish_progress("client-1", {"type": "progress"})
        self.assertEqual(await queue.get(), {"type": "progress"})

    async def test_publish_progress_handles_queue_full(self):
        class FullQueue:
            def put_nowait(self, data):
                raise asyncio.QueueFull

        progress_bus._queues["client-1"] = FullQueue()
        await progress_bus.publish_progress("client-1", {"type": "progress"})
