from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes.visualizer import _generate_image_with_gemini
from tests.support import make_chat_client, make_message_response


async def generate_image_result(response):
    with TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "generated.png"
        with patch("app.agents.nodes.visualizer.get_llm_client", return_value=make_chat_client(response)), patch(
            "app.agents.nodes.visualizer._transform_to_image_prompt",
            new=AsyncMock(return_value="optimized prompt"),
        ):
            success = await _generate_image_with_gemini("key", "desc", str(output_path))

        return success, output_path.exists(), output_path.read_bytes() if output_path.exists() else None


class VisualizerOpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_saves_base64_data_url(self):
        image_bytes = b"fake-png-bytes"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        response = make_message_response(images=[{"image_url": {"url": data_url}}])

        success, exists, saved_bytes = await generate_image_result(response)

        self.assertTrue(success)
        self.assertTrue(exists)
        self.assertEqual(saved_bytes, image_bytes)

    async def test_generate_image_returns_false_for_unusable_image_payloads(self):
        cases = (
            make_message_response("text only", images=None),
            make_message_response(images=[{"image_url": {"url": "https://example.com/image.png"}}]),
            make_message_response(images=[{"image_url": {"url": "data:image/png;base64,not-valid-base64"}}]),
        )

        for response in cases:
            with self.subTest(response=response):
                success, exists, _ = await generate_image_result(response)

                self.assertFalse(success)
                self.assertFalse(exists)

