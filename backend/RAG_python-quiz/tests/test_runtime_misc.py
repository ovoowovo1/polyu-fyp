import asyncio
import logging
import unittest
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from app.logger import logger as logger_module
from app.services.documents import crawler
from app.services.pg import pg_db
from app.services.pg import rls_context
from app.services.realtime import progress_bus
from app.utils import datetime_utils, pdf_utils
from tests.support import FakeConnection, FakeCursor


class RuntimeMiscTests(unittest.TestCase):
    def test_iso_returns_none_for_missing_datetime(self):
        self.assertIsNone(datetime_utils.iso(None))

    def test_iso_returns_isoformat_for_datetime(self):
        self.assertEqual(datetime_utils.iso(datetime(2025, 1, 2, 3, 4, 5)), "2025-01-02T03:04:05")

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

    def test_pg_db_get_conn_uses_real_dict_cursor_and_settings(self):
        rls_context.clear_current_rls_user()
        settings = SimpleNamespace(pg_dsn="postgres://example")
        with patch("app.services.pg.pg_db.get_settings", return_value=settings), patch(
            "app.services.pg.pg_db.psycopg2.connect",
            return_value="connection",
        ) as connect:
            conn = pg_db._get_conn()

        self.assertEqual(conn, "connection")
        self.assertEqual(connect.call_args.args[0], "postgres://example")
        self.assertEqual(connect.call_args.kwargs["application_name"], "pg_service")

    def test_pg_db_get_conn_sets_transaction_local_rls_user_when_present(self):
        settings = SimpleNamespace(pg_dsn="postgres://example")
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
            with patch("app.services.documents.crawler.AsyncHtmlLoader", return_value=loader), patch(
                "app.services.documents.crawler.MarkdownifyTransformer",
                return_value=transformer,
            ):
                return await crawler.load_markdown("https://example.com")

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

    async def test_publish_progress_ignores_missing_client_id(self):
        await progress_bus.publish_progress(None, {"type": "noop"})
        self.assertEqual(progress_bus._queues, {})

    async def test_publish_progress_ignores_missing_queue(self):
        await progress_bus.publish_progress("client-1", {"type": "noop"})
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
