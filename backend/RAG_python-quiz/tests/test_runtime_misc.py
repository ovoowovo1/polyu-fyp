import asyncio
import logging
import unittest
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from app.logger import logger as logger_module
from app.services import crawler, pg_db, progress_bus
from app.utils import datetime_utils, pdf_utils


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
        settings = SimpleNamespace(pg_dsn="postgres://example")
        with patch("app.services.pg_db.get_settings", return_value=settings), patch(
            "app.services.pg_db.psycopg2.connect",
            return_value="connection",
        ) as connect:
            conn = pg_db._get_conn()

        self.assertEqual(conn, "connection")
        self.assertEqual(connect.call_args.args[0], "postgres://example")
        self.assertEqual(connect.call_args.kwargs["application_name"], "pg_service")

    def test_load_markdown_transforms_async_html_documents(self):
        loader = SimpleNamespace(aload=asyncio.coroutine(lambda: ["<p>Hello</p>"]))
        transformer = SimpleNamespace(transform_documents=lambda docs: ["hello"])

        async def run():
            with patch("app.services.crawler.AsyncHtmlLoader", return_value=loader), patch(
                "app.services.crawler.MarkdownifyTransformer",
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
