from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import base64
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes import visualizer
from app.agents.schemas import ExamQuestion


def make_question(**overrides):
    data = {
        "question_id": "q-1",
        "question_type": "multiple_choice",
        "bloom_level": "analyze",
        "question_text": "What does the chart show?",
        "choices": ["A", "B", "C", "D"],
        "correct_answer_index": 0,
        "model_answer": None,
        "marks": 1,
        "marking_scheme": [],
        "rationale": "Chart interpretation",
        "image_description": None,
        "image_path": None,
        "source_chunk_ids": [],
    }
    data.update(overrides)
    return ExamQuestion(**data)


def make_client(response):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))


class VisualizerNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_classification_code_prompt_and_executor_helpers(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="unused"))])

        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value='{"image_type":"chart"}',
        ):
            image_type = await visualizer._classify_image_type("key", "Bar chart of scores")
        self.assertEqual(image_type, "chart")

        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value="not-json",
        ):
            image_type = await visualizer._classify_image_type("key", "Concept diagram")
        self.assertEqual(image_type, "illustration")

        prompt = visualizer._build_code_generation_prompt("Chart", r"C:\tmp\chart.png")
        self.assertIn("C:/tmp/chart.png", prompt)

        self.assertTrue(visualizer._execute_matplotlib_code("value = 1"))
        self.assertFalse(visualizer._execute_matplotlib_code("for"))
        self.assertFalse(visualizer._execute_matplotlib_code("raise RuntimeError('boom')"))

    async def test_chart_generation_helpers_cover_fence_stripping_and_file_existence(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="unused"))])

        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value="```python\nprint('hello')\n```",
        ):
            code = await visualizer._generate_chart_code("key", "desc", "/tmp/out.png", "model")
        self.assertEqual(code, "print('hello')")

        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value="```\nprint('hello')\n```",
        ):
            code = await visualizer._generate_chart_code("key", "desc", "/tmp/out.png", "model")
        self.assertEqual(code, "print('hello')")

        with TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "chart.png")

            def make_file(code):
                Path(output_path).write_bytes(b"png")
                return True

            with patch("app.agents.nodes.visualizer._generate_chart_code", AsyncMock(return_value="print('hello')")), patch(
                "app.agents.nodes.visualizer._execute_matplotlib_code",
                side_effect=make_file,
            ):
                self.assertTrue(await visualizer._generate_chart_with_matplotlib("key", "desc", output_path, "model"))

            with patch("app.agents.nodes.visualizer._generate_chart_code", AsyncMock(return_value="print('hello')")), patch(
                "app.agents.nodes.visualizer._execute_matplotlib_code",
                return_value=False,
            ):
                self.assertFalse(await visualizer._generate_chart_with_matplotlib("key", "desc", output_path, "model"))

    async def test_transform_prompt_and_generate_image_cover_remaining_paths(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="unused"))])
        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value="optimized prompt",
        ):
            self.assertEqual(await visualizer._transform_to_image_prompt("key", "desc"), "optimized prompt")

        with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(response)), patch(
            "app.agents.nodes.visualizer.extract_chat_completion_text",
            return_value="",
        ):
            self.assertEqual(await visualizer._transform_to_image_prompt("key", "desc"), "desc")

        with TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "image.png")
            bad_choices = SimpleNamespace(choices=None)
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(bad_choices)), patch(
                "app.agents.nodes.visualizer._transform_to_image_prompt",
                AsyncMock(return_value="prompt"),
            ):
                self.assertFalse(await visualizer._generate_image_with_gemini("key", "desc", output_path))

            missing_url = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(images=[{}], content=None))])
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(missing_url)), patch(
                "app.agents.nodes.visualizer._transform_to_image_prompt",
                AsyncMock(return_value="prompt"),
            ):
                self.assertFalse(await visualizer._generate_image_with_gemini("key", "desc", output_path))

            empty_bytes = "data:image/png;base64," + base64.b64encode(b"").decode("ascii")
            empty_response = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(images=[{"image_url": {"url": empty_bytes}}], content=None))]
            )
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=make_client(empty_response)), patch(
                "app.agents.nodes.visualizer._transform_to_image_prompt",
                AsyncMock(return_value="prompt"),
            ):
                self.assertFalse(await visualizer._generate_image_with_gemini("key", "desc", output_path))

            error_client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))))
            )
            with patch("app.agents.nodes.visualizer.get_genai_client", return_value=error_client), patch(
                "app.agents.nodes.visualizer._transform_to_image_prompt",
                AsyncMock(return_value="prompt"),
            ):
                self.assertFalse(await visualizer._generate_image_with_gemini("key", "desc", output_path))

    async def test_generate_single_image_and_visualizer_node_cover_chart_illustration_and_noop_paths(self):
        self.assertIsNone(await visualizer._generate_single_image(make_question(image_description=None), "exam-1", "model"))

        chart_question = make_question(image_description="A line chart")
        with patch("app.agents.nodes.visualizer.with_gemini_retry_async", AsyncMock(side_effect=["chart", True])), patch(
            "app.agents.nodes.visualizer.os.path.exists",
            return_value=True,
        ):
            image_path = await visualizer._generate_single_image(chart_question, "exam-1", "model")
        self.assertEqual(image_path, "/static/images/exam-1_q-1.png")

        illustration_question = make_question(question_id="q-2", image_description="A system diagram")
        with patch("app.agents.nodes.visualizer.with_gemini_retry_async", AsyncMock(side_effect=["illustration", False])), patch(
            "app.agents.nodes.visualizer.os.path.exists",
            return_value=False,
        ):
            image_path = await visualizer._generate_single_image(illustration_question, "exam-1", "model")
        self.assertIsNone(image_path)

        with patch("app.agents.nodes.visualizer.with_gemini_retry_async", AsyncMock(side_effect=RuntimeError("boom"))):
            self.assertIsNone(await visualizer._generate_single_image(chart_question, "exam-1", "model"))

        no_images = await visualizer.visualizer_node({"questions": [make_question()], "exam_id": "exam-1"})
        self.assertEqual(no_images["images"], {})

        question_with_image = make_question(image_description="A chart")
        with patch("app.agents.nodes.visualizer.get_settings", return_value=SimpleNamespace(google_ai_model="model")), patch(
            "app.agents.nodes.visualizer._generate_single_image",
            AsyncMock(return_value="/static/images/exam-1_q-1.png"),
        ):
            result = await visualizer.visualizer_node({"questions": [question_with_image], "exam_id": "exam-1"})
        self.assertEqual(result["images"]["q-1"], "/static/images/exam-1_q-1.png")
        self.assertEqual(result["questions"][0].image_path, "/static/images/exam-1_q-1.png")
