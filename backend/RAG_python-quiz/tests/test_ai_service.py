import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import ai_service
from app.services import exam_ai_grading_service, quiz_feedback_service
from app.services.llm import structured_json, text_completion


def make_chat_client(response):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))


class AiServiceFacadeTests(unittest.TestCase):
    def test_facade_exports_backward_compatible_functions(self):
        self.assertIs(ai_service.generate_structured_json, structured_json.generate_structured_json)
        self.assertIs(ai_service.generate_text_completion, text_completion.generate_text_completion)
        self.assertIs(ai_service.generate_quiz_feedback_text, quiz_feedback_service.generate_quiz_feedback_text)
        self.assertIs(ai_service.ai_grade_answer, exam_ai_grading_service.ai_grade_answer)
        self.assertIs(
            ai_service.ai_generate_exam_overall_comment,
            exam_ai_grading_service.ai_generate_exam_overall_comment,
        )


class LlmServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_structured_json_success_and_empty_response(self):
        response = SimpleNamespace()
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value='{"ok": true}',
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await structured_json.generate_structured_json(
                "prompt",
                {"type": "object"},
                operation_name="structured",
                system_prompt="system",
                temperature=0.2,
            )

        self.assertEqual(result, {"ok": True})
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(create_kwargs["temperature"], 0.2)

        with patch("app.services.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.llm.structured_json.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.llm.structured_json.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.llm.structured_json.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            with self.assertRaises(RuntimeError):
                await structured_json.generate_structured_json(
                    "prompt",
                    {"type": "object"},
                    operation_name="structured",
                )

    async def test_generate_text_completion_success_and_empty_response(self):
        response = SimpleNamespace()
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.llm.text_completion.extract_chat_completion_text",
            return_value="  hello world  ",
        ), patch(
            "app.services.llm.text_completion.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            text = await text_completion.generate_text_completion(
                "prompt",
                operation_name="text",
                system_prompt="system",
            )

        self.assertEqual(text, "hello world")
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["messages"][0], {"role": "system", "content": "system"})

        with patch("app.services.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.llm.text_completion.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.llm.text_completion.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            with self.assertRaises(RuntimeError):
                await text_completion.generate_text_completion(
                    "prompt",
                    operation_name="text",
                )


class QuizFeedbackServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_quiz_feedback_text_success_and_empty_response(self):
        response = SimpleNamespace()
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.quiz_feedback_service.get_default_llm_model_name", return_value="model"), patch(
            "app.services.quiz_feedback_service.get_llm_client",
            return_value=client,
        ), patch(
            "app.services.quiz_feedback_service.extract_chat_completion_text",
            return_value="Nice work",
        ), patch(
            "app.services.quiz_feedback_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            feedback = await quiz_feedback_service.generate_quiz_feedback_text(
                "Quiz",
                8,
                10,
                80,
                [],
                [{"question": "Why?", "user_answer_index": 1, "correct_answer_index": 2, "bloom_level": "analyze"}],
            )

        self.assertEqual(feedback, "Nice work")
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["model"], "model")
        self.assertIn("Quiz name: Quiz", create_kwargs["messages"][0]["content"])

        with patch("app.services.quiz_feedback_service.get_default_llm_model_name", return_value="model"), patch(
            "app.services.quiz_feedback_service.get_llm_client",
            return_value=client,
        ), patch(
            "app.services.quiz_feedback_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.quiz_feedback_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            with self.assertRaises(RuntimeError):
                await quiz_feedback_service.generate_quiz_feedback_text("Quiz", 8, 10, 80, [], [])


class ExamAiGradingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_grade_answer_parses_json_and_clamps_marks(self):
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")])
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        wrapped_json = """```json\n{"marks_earned": 99, "feedback": "Good", "is_correct": true, "analysis": "ok"}\n```"""
        with patch("app.services.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value=wrapped_json,
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await exam_ai_grading_service.ai_grade_answer(
                question_text="Explain 2PC",
                question_type="short_answer",
                model_answer="It blocks",
                marking_scheme=[{"criterion": "Mentions blocking", "marks": 3}],
                student_answer="It blocks",
                max_marks=3,
            )

        self.assertEqual(result["marks_earned"], 3)
        self.assertEqual(result["feedback"], "Good")

    async def test_ai_grade_answer_covers_empty_text_regex_lower_bound_and_manual_fallback(self):
        response = SimpleNamespace(choices=None)
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await exam_ai_grading_service.ai_grade_answer(
                question_text="Explain 2PC",
                question_type="short_answer",
                model_answer="It blocks",
                marking_scheme=[],
                student_answer="It blocks",
                max_marks=3,
            )
        self.assertIn("Please grade manually", result["feedback"])

        wrapped_raw = 'noise {"marks_earned": -1, "feedback": "Too low", "is_correct": false, "analysis": "ok"}'
        with patch(
            "app.services.exam_ai_grading_service.get_llm_client",
            return_value=make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")])),
        ), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value=wrapped_raw,
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await exam_ai_grading_service.ai_grade_answer(
                question_text="Explain 2PC",
                question_type="short_answer",
                model_answer="It blocks",
                marking_scheme=[],
                student_answer="It blocks",
                max_marks=3,
            )
        self.assertEqual(result["marks_earned"], 0)

        with patch(
            "app.services.exam_ai_grading_service.get_llm_client",
            return_value=make_chat_client(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")])),
        ), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value="not-json",
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            result = await exam_ai_grading_service.ai_grade_answer(
                question_text="Explain 2PC",
                question_type="short_answer",
                model_answer="It blocks",
                marking_scheme=[],
                student_answer="It blocks",
                max_marks=3,
            )
        self.assertIn("Please grade manually", result["feedback"])

        with patch("app.services.exam_ai_grading_service.with_llm_retry_async", side_effect=RuntimeError("provider down")):
            result = await exam_ai_grading_service.ai_grade_answer(
                question_text="Explain 2PC",
                question_type="short_answer",
                model_answer=None,
                marking_scheme=[],
                student_answer="",
                max_marks=3,
            )
        self.assertEqual(result["marks_earned"], 0)
        self.assertIn("Please grade manually", result["feedback"])

    async def test_ai_generate_exam_overall_comment_success_and_fallback(self):
        response = SimpleNamespace()
        client = make_chat_client(response)

        async def fake_retry(_name, func, *args, error_type=RuntimeError):
            return await func("api-key", *args)

        with patch("app.services.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value="Great effort",
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            comment = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(comment, "Great effort")

        with patch("app.services.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.exam_ai_grading_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_retry,
        ):
            comment = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(comment, "AI comment generation failed.")

        with patch("app.services.exam_ai_grading_service.with_llm_retry_async", side_effect=RuntimeError("provider down")):
            fallback = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(fallback, "AI comment generation failed.")
