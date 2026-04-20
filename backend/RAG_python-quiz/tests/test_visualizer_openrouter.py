from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import base64
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes.visualizer import _generate_image_with_gemini


def _make_response(*, images=None, content=None):
    message = SimpleNamespace(images=images, content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )


class VisualizerOpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_saves_base64_data_url(self):
        image_bytes = b"fake-png-bytes"
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        response = _make_response(images=[{"image_url": {"url": data_url}}])

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "generated.png"
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=_FakeClient(response)):
                with patch(
                    "app.agents.nodes.visualizer._transform_to_image_prompt",
                    new=AsyncMock(return_value="optimized prompt"),
                ):
                    success = await _generate_image_with_gemini("key", "desc", str(output_path))

            self.assertTrue(success)
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.read_bytes(), image_bytes)

    async def test_generate_image_returns_false_when_images_missing(self):
        response = _make_response(images=None, content="text only")

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "generated.png"
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=_FakeClient(response)):
                with patch(
                    "app.agents.nodes.visualizer._transform_to_image_prompt",
                    new=AsyncMock(return_value="optimized prompt"),
                ):
                    success = await _generate_image_with_gemini("key", "desc", str(output_path))

            self.assertFalse(success)
            self.assertFalse(output_path.exists())

    async def test_generate_image_returns_false_for_non_data_url(self):
        response = _make_response(images=[{"image_url": {"url": "https://example.com/image.png"}}])

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "generated.png"
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=_FakeClient(response)):
                with patch(
                    "app.agents.nodes.visualizer._transform_to_image_prompt",
                    new=AsyncMock(return_value="optimized prompt"),
                ):
                    success = await _generate_image_with_gemini("key", "desc", str(output_path))

            self.assertFalse(success)
            self.assertFalse(output_path.exists())

    async def test_generate_image_returns_false_for_invalid_base64(self):
        response = _make_response(images=[{"image_url": {"url": "data:image/png;base64,not-valid-base64"}}])

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "generated.png"
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=_FakeClient(response)):
                with patch(
                    "app.agents.nodes.visualizer._transform_to_image_prompt",
                    new=AsyncMock(return_value="optimized prompt"),
                ):
                    success = await _generate_image_with_gemini("key", "desc", str(output_path))

            self.assertFalse(success)
            self.assertFalse(output_path.exists())
