from unittest.mock import patch
import unittest

from app.agents.nodes.reviewer import _build_review_prompt, _run_review
from app.agents.schemas import MarkingCriterion
from tests.support import make_chat_client, make_exam_question
from tests.support import make_openai_choice as make_choice
from tests.support import make_openai_response as make_response


class ReviewerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_review_parses_valid_json(self):
        response = make_response(
            choices=[
                make_choice(
                    content='{"overall_score": 88, "is_valid": true, "decision": "PASS", "summary": "ok", "issues": []}'
                )
            ]
        )

        with patch("app.agents.nodes.reviewer.get_llm_client", return_value=make_chat_client(response)):
            result = await _run_review("test-key", "prompt", "model-name")

        self.assertEqual(result["overall_score"], 88)
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["decision"], "PASS")
        self.assertEqual(result["issues"], [])

    async def test_run_review_raises_descriptive_runtime_error_for_malformed_response(self):
        response = make_response(choices=None)

        with patch("app.agents.nodes.reviewer.get_llm_client", return_value=make_chat_client(response)):
            with self.assertRaises(RuntimeError) as ctx:
                await _run_review("test-key", "prompt", "model-name")

        message = str(ctx.exception)
        self.assertIn("returned malformed chat completion", message)
        self.assertNotIn("'NoneType' object is not subscriptable", message)

    def test_build_review_prompt_includes_open_response_context_and_rubric(self):
        question = make_exam_question(
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
        )

        prompt = _build_review_prompt("Course context", [question])

        self.assertIn("Question Type: short_answer", prompt)
        self.assertIn("Reference Answer / Model Answer: 2PC blocks participants", prompt)
        self.assertIn("Marking Scheme / Rubric: Mentions blocking behavior [1 mark(s)]", prompt)
        self.assertIn("`short_answer` and `essay` are valid open-response formats", prompt)


