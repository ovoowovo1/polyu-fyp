from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.agents.nodes.reviewer import _build_review_prompt, _run_review
from app.agents.schemas import ExamQuestion, MarkingCriterion


def make_response(*, choices, model="test-model"):
    return SimpleNamespace(model=model, choices=choices)


def make_choice(*, content=None, finish_reason="stop", refusal=None):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, refusal=refusal),
        finish_reason=finish_reason,
    )


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )


class ReviewerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_review_parses_valid_json(self):
        response = make_response(
            choices=[
                make_choice(
                    content='{"overall_score": 88, "is_valid": true, "decision": "PASS", "summary": "ok", "issues": []}'
                )
            ]
        )

        with patch("app.agents.nodes.reviewer.get_genai_client", return_value=_FakeClient(response)):
            result = await _run_review("test-key", "prompt", "model-name")

        self.assertEqual(result["overall_score"], 88)
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["issues"], [])

    async def test_run_review_raises_descriptive_runtime_error_for_malformed_response(self):
        response = make_response(choices=None)

        with patch("app.agents.nodes.reviewer.get_genai_client", return_value=_FakeClient(response)):
            with self.assertRaises(RuntimeError) as ctx:
                await _run_review("test-key", "prompt", "model-name")

        message = str(ctx.exception)
        self.assertIn("憿撖拇 returned malformed chat completion", message)
        self.assertNotIn("'NoneType' object is not subscriptable", message)

    def test_build_review_prompt_includes_open_response_context_and_rubric(self):
        question = ExamQuestion(
            question_id="q_short_1",
            question_type="short_answer",
            bloom_level="analyze",
            question_text="Explain why 2PC favors consistency over availability.",
            model_answer="2PC blocks participants when the coordinator is unavailable, which preserves consistency.",
            marks=2,
            marking_scheme=[
                MarkingCriterion(
                    criterion="Mentions blocking behavior",
                    marks=1,
                    explanation="The answer should mention coordinator failure or waiting states.",
                )
            ],
            rationale="Tests understanding of distributed transaction trade-offs.",
            image_description=None,
            image_path=None,
            source_chunk_ids=[],
        )

        prompt = _build_review_prompt("Course context", [question])

        self.assertIn("Question Type: short_answer", prompt)
        self.assertIn("Reference Answer / Model Answer: 2PC blocks participants", prompt)
        self.assertIn("Marking Scheme / Rubric: Mentions blocking behavior [1 mark(s)]", prompt)
        self.assertIn("`short_answer` and `essay` are valid open-response formats", prompt)
