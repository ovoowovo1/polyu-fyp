import json
import unittest
from unittest.mock import patch

import app.agents.nodes.generator as generator_module


def _build_state(
    *,
    question_types=None,
    topic="Database Security and Availability",
    exam_name="",
):
    return {
        "context": "CAP theorem, distributed transactions, and high availability trade-offs.",
        "num_questions": 3,
        "question_types": question_types
        or {
            "multiple_choice": 1,
            "short_answer": 1,
            "essay": 1,
        },
        "custom_prompt": "",
        "difficulty": "difficult",
        "topic": topic,
        "feedback": "Reviewer requested a rewrite with better structure.",
        "retry_count": 1,
        "exam_id": "exam_test_123",
        "exam_name": exam_name,
    }


def _mc_item():
    return {
        "question_type": "multiple_choice",
        "bloom_level": "analyze",
        "question_text": "Why does 2PC favor consistency over availability during failures?",
        "choices": [
            "It avoids blocking by allowing unilateral commits.",
            "It blocks participants to preserve a consistent commit decision.",
            "It guarantees partitions never happen.",
            "It always prioritizes local autonomy over agreement.",
        ],
        "correct_answer_index": 1,
        "marks": 1,
        "marking_criteria": ["Identifies that 2PC blocks to keep commit/abort decisions consistent."],
        "rationale": "Tests the consistency-availability trade-off in distributed commits.",
        "image_description": None,
    }


def _sa_item():
    return {
        "question_type": "short_answer",
        "bloom_level": "analyze",
        "question_text": "Explain one operational drawback of 2PC in a partitioned network.",
        "model_answer": "2PC can block participants while they wait for the coordinator, which hurts availability.",
        "marks": 2,
        "marking_criteria": ["Mentions blocking behavior or coordinator dependence."],
        "rationale": "Checks conceptual understanding of failure handling.",
        "image_description": None,
    }


def _essay_item():
    return {
        "question_type": "essay",
        "bloom_level": "evaluate",
        "question_text": "Evaluate whether 2PC is suitable for internet-scale systems that value availability.",
        "model_answer": (
            "2PC is often unsuitable because it coordinates a global commit decision by blocking participants during "
            "uncertainty. That behavior preserves consistency but can sharply reduce availability under partitions "
            "or coordinator failure. Internet-scale systems commonly prefer patterns such as sagas or compensating "
            "transactions, which relax immediate consistency and trade some simplicity for resilience."
        ),
        "marks": 5,
        "marking_criteria": [
            "Explains the blocking or coordinator dependency in 2PC.",
            "Connects the behavior to availability trade-offs in distributed systems.",
        ],
        "rationale": "Requires evaluation of trade-offs using course concepts.",
        "image_description": None,
    }


def _section_payload(question_type, items):
    return json.dumps({generator_module.SECTION_TO_ARRAY[question_type]: items})


class GeneratorRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_generator_retries_only_failed_multiple_choice_section(self):
        call_counts = {"multiple_choice": 0, "short_answer": 0, "essay": 0}

        async def fake_retry(operation_name, _operation_func, prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            self.assertIn(generator_module.SECTION_TO_ARRAY[section_name], prompt)
            if section_name != "multiple_choice":
                self.assertIn("prefer structured rubric objects", prompt)
                self.assertIn("criterion", prompt)
                self.assertIn("explanation", prompt)
            call_counts[section_name] += 1
            if section_name == "multiple_choice":
                if call_counts[section_name] == 1:
                    return '{"multiple_choice_questions":[{"question_type":"multiple_choice"'
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                return _section_payload("short_answer", [_sa_item()])
            return _section_payload("essay", [_essay_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(_build_state())

        self.assertEqual(call_counts["multiple_choice"], 2)
        self.assertEqual(call_counts["short_answer"], 1)
        self.assertEqual(call_counts["essay"], 1)
        self.assertEqual(len(result["questions"]), 3)
        self.assertEqual(result["exam_name"], "Database Security and Availability")

    async def test_generator_retries_only_failed_short_answer_section(self):
        call_counts = {"multiple_choice": 0, "short_answer": 0, "essay": 0}

        async def fake_retry(operation_name, _operation_func, prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            call_counts[section_name] += 1
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                if call_counts[section_name] == 1:
                    return _section_payload("short_answer", ["Bare string item"])
                self.assertIn("Previous short_answer generation returned an unusable payload.", prompt)
                return _section_payload("short_answer", [_sa_item()])
            return _section_payload("essay", [_essay_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(_build_state())

        self.assertEqual(call_counts["multiple_choice"], 1)
        self.assertEqual(call_counts["short_answer"], 2)
        self.assertEqual(call_counts["essay"], 1)
        self.assertEqual(
            [question.question_type for question in result["questions"]],
            ["multiple_choice", "short_answer", "essay"],
        )

    async def test_generator_retries_only_failed_essay_section_for_count_mismatch(self):
        call_counts = {"multiple_choice": 0, "short_answer": 0, "essay": 0}

        async def fake_retry(operation_name, _operation_func, prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            call_counts[section_name] += 1
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                return _section_payload("short_answer", [_sa_item()])
            if call_counts[section_name] == 1:
                return _section_payload("essay", [])
            self.assertIn("Previous essay generation returned an unusable payload.", prompt)
            return _section_payload("essay", [_essay_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(_build_state())

        self.assertEqual(call_counts["multiple_choice"], 1)
        self.assertEqual(call_counts["short_answer"], 1)
        self.assertEqual(call_counts["essay"], 2)
        self.assertEqual(len(result["questions"]), 3)

    async def test_generator_fails_entire_exam_when_one_section_never_recovers(self):
        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                return _section_payload("short_answer", [_sa_item()])
            return '{"essay_questions":[{"question_type":"essay"'

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ), self.assertLogs("app.agents.nodes.generator", level="ERROR") as log_context:
            with self.assertRaises(RuntimeError) as ctx:
                await generator_module.generator_node(_build_state())

        message = str(ctx.exception)
        self.assertIn("section 'essay'", message)
        self.assertIn("line 1 column", message)
        self.assertIn("char ", message)
        combined_logs = "\n".join(log_context.output)
        self.assertIn("JSON error context:", combined_logs)
        self.assertIn("Full invalid payload:", combined_logs)

    async def test_exam_name_uses_explicit_state_value_before_topic(self):
        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                return _section_payload("short_answer", [_sa_item()])
            return _section_payload("essay", [_essay_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(
                _build_state(topic="Topic Name", exam_name="Teacher Provided Exam Name")
            )

        self.assertEqual(result["exam_name"], "Teacher Provided Exam Name")

    async def test_exam_name_falls_back_to_generated_exam_when_state_and_topic_are_empty(self):
        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            return _section_payload("multiple_choice", [_mc_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(
                _build_state(
                    question_types={"multiple_choice": 1, "short_answer": 0, "essay": 0},
                    topic="",
                    exam_name="",
                )
            )

        self.assertEqual(result["exam_name"], "Generated Exam")
        self.assertEqual(len(result["questions"]), 1)

    async def test_generator_enforces_fixed_marks_and_normalized_rubrics(self):
        mc_item = {
            **_mc_item(),
            "marks": 5,
            "marking_criteria": ["This rubric should be ignored for MCQ."],
        }
        short_answer_item = {
            **_sa_item(),
            "marks": 5,
            "marking_criteria": [
                {"criterion": "Explains blocking", "marks": 5, "explanation": "Mentions coordinator wait."},
                {"criterion": "Connects to availability", "marks": 1, "explanation": "Links blocking to downtime."},
            ],
        }
        essay_item = {
            **_essay_item(),
            "marks": 10,
            "marking_criteria": [
                {"criterion": "Analyzes consistency trade-off", "marks": 4, "explanation": "Covers consistency."},
                {"criterion": "Analyzes availability trade-off", "marks": 4, "explanation": "Covers availability."},
                {"criterion": "Evaluates alternatives", "marks": 4, "explanation": "Mentions sagas or compensating transactions."},
            ],
        }

        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [mc_item])
            if section_name == "short_answer":
                return _section_payload("short_answer", [short_answer_item])
            return _section_payload("essay", [essay_item])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(_build_state())

        mc_question, short_question, essay_question = result["questions"]
        self.assertEqual([question.marks for question in result["questions"]], [1, 3, 5])
        self.assertEqual(mc_question.marking_scheme, [])
        self.assertEqual(sum(criterion.marks for criterion in short_question.marking_scheme), 3)
        self.assertEqual(sum(criterion.marks for criterion in essay_question.marking_scheme), 5)
        self.assertEqual(
            [criterion.criterion for criterion in short_question.marking_scheme],
            ["Explains blocking", "Connects to availability"],
        )
        self.assertEqual(
            [criterion.explanation for criterion in short_question.marking_scheme],
            ["Mentions coordinator wait.", "Links blocking to downtime."],
        )
        self.assertEqual(
            [criterion.explanation for criterion in essay_question.marking_scheme],
            ["Covers consistency.", "Covers availability.", "Mentions sagas or compensating transactions."],
        )

    async def test_multiple_choice_generation_succeeds_without_marking_criteria(self):
        mc_item = _mc_item()
        mc_item.pop("marking_criteria")
        mc_item["marks"] = 7

        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            return _section_payload("multiple_choice", [mc_item])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(
                _build_state(
                    question_types={"multiple_choice": 1, "short_answer": 0, "essay": 0},
                    topic="",
                )
            )

        self.assertEqual(len(result["questions"]), 1)
        question = result["questions"][0]
        self.assertEqual(question.question_type, "multiple_choice")
        self.assertEqual(question.marks, 1)
        self.assertEqual(question.marking_scheme, [])

    async def test_string_only_marking_criteria_still_normalize_with_explanation_fallback(self):
        async def fake_retry(operation_name, _operation_func, _prompt, _model_name, _schema, section_name, error_type=RuntimeError):
            self.assertIn(section_name, operation_name)
            if section_name == "multiple_choice":
                return _section_payload("multiple_choice", [_mc_item()])
            if section_name == "short_answer":
                return _section_payload("short_answer", [_sa_item()])
            return _section_payload("essay", [_essay_item()])

        with patch("app.agents.nodes.generator.with_llm_retry_async", side_effect=fake_retry), patch(
            "app.agents.nodes.generator.get_default_llm_model_name", return_value="test-model"
        ):
            result = await generator_module.generator_node(_build_state())

        short_question = result["questions"][1]
        essay_question = result["questions"][2]
        self.assertEqual(
            [(criterion.criterion, criterion.explanation) for criterion in short_question.marking_scheme],
            [("Mentions blocking behavior or coordinator dependence.", "Mentions blocking behavior or coordinator dependence.")],
        )
        self.assertEqual(
            [(criterion.criterion, criterion.explanation) for criterion in essay_question.marking_scheme],
            [
                ("Explains the blocking or coordinator dependency in 2PC.", "Explains the blocking or coordinator dependency in 2PC."),
                ("Connects the behavior to availability trade-offs in distributed systems.", "Connects the behavior to availability trade-offs in distributed systems."),
            ],
        )


