import unittest
from unittest.mock import patch

from app.utils import api_key_manager


class RetryWrapperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_keys = list(api_key_manager._llm_keys)
        self.original_index = api_key_manager._llm_index

    def tearDown(self):
        api_key_manager._llm_keys = self.original_keys
        api_key_manager._llm_index = self.original_index

    async def test_async_retry_reports_attempt_count_and_root_cause(self):
        api_key_manager._llm_keys = ["key-1", "key-2"]
        api_key_manager._llm_index = 0

        async def always_fail(api_key):
            raise RuntimeError(f"root cause from {api_key}")

        with self.assertRaises(RuntimeError) as ctx:
            await api_key_manager.with_llm_retry_async("topic_review", always_fail, retry_delay=0)

        message = str(ctx.exception)
        self.assertIn("attempted 2/2 configured keys", message)
        self.assertIn("root cause from key-2", message)

    async def test_async_retry_reports_no_configured_keys(self):
        async def should_not_run(api_key):
            raise AssertionError("should not be called")

        with patch("app.utils.api_key_manager.reset_llm_key_index"), patch(
            "app.utils.api_key_manager.get_llm_keys_count", return_value=0
        ), patch("app.utils.api_key_manager.get_current_llm_api_key", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                await api_key_manager.with_llm_retry_async("topic_review", should_not_run, retry_delay=0)

        self.assertEqual(str(ctx.exception), "No API keys configured for topic_review")


class RetryWrapperSyncTests(unittest.TestCase):
    def setUp(self):
        self.original_keys = list(api_key_manager._llm_keys)
        self.original_index = api_key_manager._llm_index

    def tearDown(self):
        api_key_manager._llm_keys = self.original_keys
        api_key_manager._llm_index = self.original_index

    def test_sync_retry_reports_attempt_count_and_root_cause(self):
        api_key_manager._llm_keys = ["key-1", "key-2"]
        api_key_manager._llm_index = 0

        def always_fail(api_key):
            raise RuntimeError(f"root cause from {api_key}")

        with self.assertRaises(RuntimeError) as ctx:
            api_key_manager.with_llm_retry_sync("topic_review", always_fail, retry_delay=0)

        message = str(ctx.exception)
        self.assertIn("attempted 2/2 configured keys", message)
        self.assertIn("root cause from key-2", message)
