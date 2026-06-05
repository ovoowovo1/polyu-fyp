from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.nodes import reviewer
from app.agents.schemas import MarkingCriterion
from tests.support import make_chat_client, make_exam_question, make_message_response


def make_question(**overrides):
    defaults = {
        "bloom_level": "analyze",
        "question_text": "Why does 2PC block?",
        "model_answer": "Because the coordinator may be unavailable.",
        "marking_scheme": [MarkingCriterion(criterion="Mentions blocking", marks=2, explanation="Explains coordinator wait states.")],
        "rationale": "Tests understanding of commit coordination.",
        "marks": 2,
    }
    defaults.update(overrides)
    return make_exam_question(**defaults)


def _review_client():
    return make_chat_client(make_message_response())


@contextmanager
def patched_review_text(text, client=None):
    with patch("app.agents.nodes.reviewer.get_llm_client", return_value=client or _review_client()), patch(
        "app.agents.nodes.reviewer.extract_chat_completion_text",
        return_value=text,
    ):
        yield


class ReviewerNodeTests(unittest.IsolatedAsyncioTestCase):
    def test_review_prompt_and_helpers_cover_image_and_custom_paths(self):
        no_scheme = make_question(marking_scheme=[], image_description="Show the system architecture.", image_path="/static/images/q-1.png")
        missing_image = make_question(question_id="q-2", image_description="Chart of throughput", image_path=None)

        prompt = reviewer._build_review_prompt(
            "Course context",
            [no_scheme, missing_image],
            custom_prompt="Include architecture reasoning.",
            has_images=True,
        )

        self.assertIn("N/A", prompt)
        self.assertIn("Image attached below", prompt)
        self.assertIn("Image generation failed", prompt)
        self.assertIn("User Custom Requirements", prompt)
        self.assertIn("Image Review Instructions", prompt)

        self.assertEqual(reviewer._strip_code_fences("```json\n{}\n```"), "{}")
        self.assertEqual(reviewer._strip_code_fences("```\n{}\n```"), "{}")
        self.assertEqual(reviewer._get_absolute_image_path("plain/path.png"), "plain/path.png")
        self.assertIn("Mentions blocking", reviewer._format_marking_scheme(make_question()))

    async def test_load_image_and_run_review_cover_parsing_edge_cases(self):
        with TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "figure.jpg"
            image_path.write_bytes(b"image-bytes")

            mime_type, encoded = reviewer._load_image_as_base64(str(image_path))
            self.assertEqual(mime_type, "image/jpeg")
            self.assertTrue(encoded)

            with patched_review_text(
                'prefix {"overall_score": 90, "is_valid": true, "decision": "PASS", "summary": "ok", "issues": []} suffix'
            ):
                result = await reviewer._run_review("key", "prompt", "model")
            self.assertEqual(result["decision"], "PASS")

            for response_text in ("   ", "not-json", "[]", 'prefix {"bad": } suffix'):
                with self.subTest(response_text=response_text), patched_review_text(response_text):
                    with self.assertRaises(RuntimeError):
                        await reviewer._run_review("key", "prompt", "model")

    async def test_run_review_handles_missing_and_failed_images(self):
        with patch("app.agents.nodes.reviewer.get_llm_client", return_value=_review_client()), patch(
            "app.agents.nodes.reviewer.extract_chat_completion_text",
            return_value='{"overall_score": 88, "is_valid": true, "decision": "PASS", "summary": "ok", "issues": []}',
        ), patch(
            "app.agents.nodes.reviewer.os.path.exists",
            side_effect=lambda path: path.endswith("bad.png"),
        ), patch(
            "app.agents.nodes.reviewer._load_image_as_base64",
            side_effect=RuntimeError("bad image"),
        ):
            result = await reviewer._run_review(
                "key",
                "prompt",
                "model",
                image_paths=["/static/images/missing.png", "/static/images/bad.png"],
            )

        self.assertEqual(result["overall_score"], 88)

    async def test_run_review_appends_inline_image_parts_when_image_load_succeeds(self):
        client = make_chat_client(make_message_response())
        with patch("app.agents.nodes.reviewer.get_llm_client", return_value=client), patch(
            "app.agents.nodes.reviewer.extract_chat_completion_text",
            return_value='{"overall_score": 88, "is_valid": true, "decision": "PASS", "summary": "ok", "issues": []}',
        ), patch(
            "app.agents.nodes.reviewer.os.path.exists",
            return_value=True,
        ), patch(
            "app.agents.nodes.reviewer._load_image_as_base64",
            return_value=("image/png", "ZmFrZQ=="),
        ):
            await reviewer._run_review("key", "prompt", "model", image_paths=["/static/images/chart.png"])

        captured = client.chat.completions.create.call_args.kwargs
        self.assertEqual(len(captured["messages"][0]["content"]), 2)

    async def test_reviewer_node_covers_no_questions_and_exception_path(self):
        state = {"questions": [], "warnings": []}
        result = await reviewer.reviewer_node(state)
        self.assertFalse(result["review_result"].is_valid)
        self.assertTrue(result["is_complete"])

        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(side_effect=RuntimeError("review failed")),
        ):
            failed = await reviewer.reviewer_node({"questions": [make_question()], "warnings": []})

        self.assertTrue(failed["is_complete"])
        self.assertIn("Review failed", failed["warnings"][0])

    async def test_reviewer_node_covers_pass_research_retry_and_rewrite_paths(self):
        question = make_question()
        base_state = {"context": "Context", "questions": [question], "warnings": [], "retry_count": 0, "max_retries": 2}

        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(return_value={"overall_score": 95, "is_valid": True, "decision": "PASS", "summary": "Great", "issues": []}),
        ):
            passed = await reviewer.reviewer_node({**base_state, "questions": [make_question(image_path="/static/images/q-1.png")]})
        self.assertTrue(passed["is_complete"])

        research_payload = {
            "overall_score": 60,
            "is_valid": False,
            "decision": "RESEARCH",
            "research_goal": "Need more CAP theorem context",
            "summary": "Need more source material",
            "issues": [],
        }
        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(return_value=research_payload),
        ):
            research = await reviewer.reviewer_node({**base_state, "search_iterations": 0, "max_search_iterations": 2})
        self.assertFalse(research["is_complete"])
        self.assertEqual(research["research_goal"], "Need more CAP theorem context")

        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(return_value={**research_payload, "overall_score": 80}),
        ):
            limit_pass = await reviewer.reviewer_node({**base_state, "search_iterations": 2, "max_search_iterations": 2})
        self.assertTrue(limit_pass["is_complete"])

        rewrite_payload = {
            "overall_score": 50,
            "is_valid": False,
            "decision": "REWRITE",
            "summary": "Needs fixes",
            "issues": [{"question_id": "q-1", "issue_type": "marking_unclear", "description": "Rubric weak", "suggestion": "Add clearer rubric"}],
        }
        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(return_value=rewrite_payload),
        ):
            rewrite = await reviewer.reviewer_node(dict(base_state))
        self.assertFalse(rewrite["is_complete"])
        self.assertEqual(rewrite["retry_count"], 1)
        self.assertIn("Rubric weak", rewrite["feedback"])

        with patch("app.agents.nodes.reviewer.get_default_llm_model_name", return_value="model"), patch(
            "app.agents.nodes.reviewer.with_llm_retry_async",
            AsyncMock(return_value=rewrite_payload),
        ):
            exhausted = await reviewer.reviewer_node({**base_state, "retry_count": 2, "max_retries": 2})
        self.assertTrue(exhausted["is_complete"])
        self.assertIn("maximum number of retries", exhausted["warnings"][0])


