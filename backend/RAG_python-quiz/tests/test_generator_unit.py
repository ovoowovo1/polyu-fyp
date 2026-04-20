import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.agents.nodes.generator as generator_module


class GeneratorUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_schema_prompt_and_json_helpers(self):
        mc_schema = generator_module._build_question_item_schema(
            "multiple_choice",
            bloom_enum=["remember", "apply"],
        )
        essay_schema = generator_module._build_question_item_schema(
            "essay",
            bloom_enum=["analyze"],
            answer_description="Reference answer",
        )
        section_schema = generator_module._build_generator_section_schema("essay", 2)

        self.assertIn("choices", mc_schema["properties"])
        self.assertEqual(essay_schema["properties"]["model_answer"]["description"], "Reference answer")
        self.assertEqual(section_schema["properties"]["essay_questions"]["minItems"], 2)

        prompt = generator_module._build_section_generator_prompt(
            context="context",
            difficulty="unknown",
            topic="Topic",
            question_type="short_answer",
            count=2,
            feedback="Fix rubric",
            custom_prompt="Be concise",
        )
        self.assertIn("Fix rubric", prompt)
        self.assertIn("Be concise", prompt)
        self.assertIn("understand", prompt)

        self.assertEqual(generator_module._strip_code_fences("```json\n{}\n```"), "{}")
        self.assertEqual(generator_module._strip_code_fences("```\n{}\n```"), "{}")
        self.assertEqual(
            generator_module._extract_outermost_json_object('noise {"a":"{brace}","b":1} tail'),
            '{"a":"{brace}","b":1}',
        )
        self.assertEqual(
            generator_module._extract_outermost_json_object('noise {"a":"quote \\\\\\" inner","b":1} tail'),
            '{"a":"quote \\\\\\" inner","b":1}',
        )
        self.assertIsNone(generator_module._extract_outermost_json_object("no braces here"))
        self.assertIn("char_window", generator_module._build_json_error_context("abcdef", 3, window=2))

        err = json.JSONDecodeError("bad", "{}", 1)
        self.assertIn("invalid JSON payload", generator_module._format_json_error_message(err))

    def test_payload_parsing_and_normalization_errors(self):
        with self.assertRaises(generator_module.GeneratorPayloadError):
            generator_module._parse_generator_payload("")

        payload = generator_module._parse_generator_payload('before {"multiple_choice_questions": []} after')
        self.assertEqual(payload["multiple_choice_questions"], [])

        with self.assertRaises(generator_module.GeneratorPayloadError):
            generator_module._parse_generator_payload('before {"multiple_choice_questions": [} after')

        with self.assertRaises(generator_module.GeneratorPayloadError):
            generator_module._parse_generator_payload("[]")

        normalized = generator_module._normalize_question_item(
            {
                "bloom_level": "remember",
                "question_text": "What is SQL?",
                "choices": ["A", "B", "C", "D"],
                "correct_answer_index": 1,
                "rationale": "Tests recall",
            },
            array_name="multiple_choice_questions",
            question_type="multiple_choice",
            question_index=0,
        )
        self.assertEqual(normalized["question_type"], "multiple_choice")
        self.assertEqual(normalized["marks"], 1)
        self.assertEqual(normalized["marking_criteria"], [])

        invalid_cases = [
            (
                {"question_type": "essay", "bloom_level": "remember", "question_text": "x", "rationale": "y"},
                "multiple_choice",
            ),
            (
                {"question_type": "multiple_choice", "bloom_level": "", "question_text": "x", "rationale": "y"},
                "multiple_choice",
            ),
            (
                {
                    "question_type": "multiple_choice",
                    "bloom_level": "remember",
                    "question_text": "x",
                    "choices": ["A", "B", "C"],
                    "correct_answer_index": 1,
                    "rationale": "y",
                },
                "multiple_choice",
            ),
            (
                {
                    "question_type": "multiple_choice",
                    "bloom_level": "remember",
                    "question_text": "x",
                    "choices": ["A", "B", "C", "D"],
                    "correct_answer_index": "1",
                    "rationale": "y",
                },
                "multiple_choice",
            ),
            (
                {
                    "question_type": "short_answer",
                    "bloom_level": "remember",
                    "question_text": "x",
                    "model_answer": "",
                    "marking_criteria": ["ok"],
                    "rationale": "y",
                },
                "short_answer",
            ),
            (
                {
                    "question_type": "essay",
                    "bloom_level": "evaluate",
                    "question_text": "x",
                    "model_answer": "ok",
                    "marking_criteria": [""],
                    "rationale": "y",
                },
                "essay",
            ),
            (
                {
                    "question_type": "essay",
                    "bloom_level": "evaluate",
                    "question_text": "x",
                    "model_answer": "ok",
                    "marking_criteria": ["criterion"],
                    "rationale": "y",
                    "image_description": 123,
                },
                "essay",
            ),
        ]
        for item, question_type in invalid_cases:
            with self.subTest(item=item):
                with self.assertRaises(generator_module.GeneratorPayloadError):
                    generator_module._normalize_question_item(
                        item,
                        array_name=f"{question_type}_questions",
                        question_type=question_type,
                        question_index=0,
                    )

        with self.assertRaises(generator_module.GeneratorPayloadError):
            generator_module._validate_marking_criteria([], array_name="essay_questions", question_index=0)

        normalized_section = generator_module._normalize_generator_section_payload(
            {
                "questions": [
                    {
                        "question_type": "essay",
                        "bloom_level": "evaluate",
                        "question_text": "Discuss",
                        "model_answer": "Answer",
                        "marking_criteria": ["criterion"],
                        "rationale": "Tests evaluation",
                    }
                ]
            },
            question_type="essay",
            expected_count=1,
        )
        self.assertEqual(normalized_section[0]["marks"], 5)

        for payload in ({}, {"essay_questions": "bad"}, {"essay_questions": []}):
            with self.subTest(payload=payload):
                with self.assertRaises(generator_module.GeneratorPayloadError):
                    generator_module._normalize_generator_section_payload(
                        payload,
                        question_type="essay",
                        expected_count=1,
                    )

    async def test_request_section_output_handles_strict_fallback_and_failures(self):
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")])

        with patch(
            "app.agents.nodes.generator._create_section_response",
            new=AsyncMock(side_effect=[RuntimeError("strict schema unsupported"), response]),
        ), patch(
            "app.agents.nodes.generator.extract_chat_completion_text",
            return_value='{"multiple_choice_questions": []}',
        ):
            text = await generator_module._request_section_generator_output(
                "api-key",
                "prompt",
                "model",
                {"type": "object"},
                "multiple_choice",
            )
        self.assertIn("multiple_choice_questions", text)

        for finish_reason, expected in (("content_filter", "blocked"), ("length", "empty content")):
            with self.subTest(finish_reason=finish_reason):
                response = SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason)])
                with patch(
                    "app.agents.nodes.generator._create_section_response",
                    new=AsyncMock(return_value=response),
                ), patch(
                    "app.agents.nodes.generator.extract_chat_completion_text",
                    return_value="" if finish_reason == "length" else '{"ok":1}',
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        await generator_module._request_section_generator_output(
                            "api-key",
                            "prompt",
                            "model",
                            {"type": "object"},
                            "essay",
                        )
                self.assertIn(expected, str(ctx.exception))

        with patch(
            "app.agents.nodes.generator._create_section_response",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            with self.assertRaises(RuntimeError):
                await generator_module._request_section_generator_output(
                    "api-key",
                    "prompt",
                    "model",
                    {"type": "object"},
                    "essay",
                )

    async def test_create_section_response_uses_client_and_to_thread(self):
        create_fn = object()
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn))
        )

        with patch(
            "app.agents.nodes.generator.get_genai_client",
            return_value=fake_client,
        ), patch(
            "app.agents.nodes.generator.asyncio.to_thread",
            new=AsyncMock(return_value="response"),
        ) as to_thread:
            result = await generator_module._create_section_response(
                api_key="api-key",
                prompt="prompt",
                model_name="model",
                schema={"type": "object"},
                section_name="essay",
                strict=True,
            )

        self.assertEqual(result, "response")
        self.assertIs(to_thread.await_args.args[0], create_fn)

    async def test_generate_question_section_retry_and_terminal_failure(self):
        with patch(
            "app.agents.nodes.generator.with_gemini_retry_async",
            new=AsyncMock(side_effect=['{"multiple_choice_questions":[{"question_type":"multiple_choice"}]}'] * 3),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await generator_module._generate_question_section(
                    context="ctx",
                    difficulty="medium",
                    topic="Topic",
                    question_type="multiple_choice",
                    count=1,
                    base_feedback="",
                    custom_prompt="",
                    model_name="model",
                )
        self.assertIn("generation parse/validation failure after 3 attempts", str(ctx.exception))

        valid_payload = json.dumps(
            {
                "essay_questions": [
                    {
                        "question_type": "essay",
                        "bloom_level": "evaluate",
                        "question_text": "Discuss trade-offs",
                        "model_answer": "Answer",
                        "marking_criteria": ["criterion"],
                        "rationale": "Tests evaluation",
                    }
                ]
            }
        )
        with patch(
            "app.agents.nodes.generator.with_gemini_retry_async",
            new=AsyncMock(return_value=valid_payload),
        ):
            result = await generator_module._generate_question_section(
                context="ctx",
                difficulty="medium",
                topic="Topic",
                question_type="essay",
                count=1,
                base_feedback="feedback",
                custom_prompt="custom",
                model_name="model",
            )
        self.assertEqual(result[0]["marks"], 5)

        with self.assertRaises(RuntimeError) as ctx:
            await generator_module._generate_question_section(
                context="ctx",
                difficulty="medium",
                topic="Topic",
                question_type="essay",
                count=1,
                base_feedback="",
                custom_prompt="",
                model_name="model",
                max_generation_attempts=0,
            )
        self.assertIn("failed without returning", str(ctx.exception))

    def test_mark_distribution_and_exam_question_builders(self):
        self.assertEqual(generator_module._build_exam_name({"exam_name": "  Final Exam "}, "Topic"), "Final Exam")
        self.assertEqual(generator_module._build_exam_name({}, "Topic"), "Topic")
        self.assertEqual(generator_module._build_exam_name({}, ""), "Generated Exam")

        self.assertEqual(generator_module._distribute_marks(5, 0), [])
        self.assertEqual(generator_module._distribute_marks(5, 3), [2, 2, 1])
        self.assertEqual(generator_module._distribute_marks(5, 2, [2, 1]), [3, 2])

        self.assertEqual(generator_module._build_marking_scheme("multiple_choice", ["ignored"]), [])
        scheme = generator_module._build_marking_scheme(
            "short_answer",
            [
                {"criterion": "Accuracy", "explanation": "Correct facts", "marks": 5},
                {"criterion": "Clarity", "explanation": "Clear explanation", "marks": 1},
            ],
        )
        self.assertEqual(sum(item.marks for item in scheme), 3)

        exact_scheme = generator_module._build_marking_scheme(
            "short_answer",
            [
                {"criterion": "Accuracy", "explanation": "Correct facts", "marks": 2},
                {"criterion": "Clarity", "explanation": "Clear explanation", "marks": 1},
            ],
        )
        self.assertEqual([item.marks for item in exact_scheme], [2, 1])

        fallback_scheme = generator_module._build_marking_scheme(
            "essay",
            [{"criterion": "", "explanation": "", "marks": 0}],
        )
        self.assertEqual(fallback_scheme[0].criterion, "Criterion 1")

        with self.assertLogs("app.agents.nodes.generator", level="WARNING"):
            question = generator_module._build_exam_question(
                "multiple_choice",
                {
                    "bloom_level": "remember",
                    "question_text": "MCQ",
                    "choices": ["A", "B", "C", "D"],
                    "correct_answer_index": 99,
                    "rationale": "why",
                },
            )
        self.assertEqual(question.correct_answer_index, 0)

        essay = generator_module._build_exam_question(
            "essay",
            {
                "bloom_level": "evaluate",
                "question_text": "Essay",
                "model_answer": "Answer",
                "marking_criteria": ["criterion"],
                "rationale": "why",
                "image_description": "diagram",
            },
        )
        self.assertEqual(essay.model_answer, "Answer")
        self.assertEqual(essay.image_description, "diagram")

    async def test_generator_node_default_path_and_validation(self):
        with self.assertRaises(ValueError):
            await generator_module.generator_node({})

        mc_payload = json.dumps(
            {
                "multiple_choice_questions": [
                    {
                        "question_type": "multiple_choice",
                        "bloom_level": "remember",
                        "question_text": "What is SQL?",
                        "choices": ["A", "B", "C", "D"],
                        "correct_answer_index": 1,
                        "rationale": "Recall",
                    }
                ]
            }
        )
        with patch(
            "app.agents.nodes.generator.with_gemini_retry_async",
            new=AsyncMock(return_value=mc_payload),
        ), patch(
            "app.agents.nodes.generator.get_default_model_name",
            return_value="model",
        ):
            result = await generator_module.generator_node(
                {
                    "context": "course material",
                    "num_questions": 1,
                    "difficulty": "easy",
                    "topic": "",
                    "custom_prompt": "teacher note",
                }
            )

        self.assertEqual(result["exam_name"], "Generated Exam")
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["feedback"], "")
