import unittest
from unittest.mock import patch

from app.services.ai import exam_ai_grading_service, exam_grading_prompts, exam_grading_runtime, quiz_feedback_service
from app.services.ai.llm import multimodal, structured_json, text_completion
from tests.support import fake_llm_retry, make_chat_client, make_completion_response


class LlmServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_structured_json_success_and_empty_response(self):
        response = make_completion_response()
        client = make_chat_client(response)

        with patch("app.services.ai.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.structured_json.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.structured_json.extract_chat_completion_text",
            return_value='{"ok": true}',
        ), patch(
            "app.services.ai.llm.structured_json.with_llm_retry_async",
            side_effect=fake_llm_retry,
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

        with patch("app.services.ai.llm.structured_json.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.structured_json.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.structured_json.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.ai.llm.structured_json.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            with self.assertRaises(RuntimeError):
                await structured_json.generate_structured_json(
                    "prompt",
                    {"type": "object"},
                    operation_name="structured",
                )

    async def test_generate_text_completion_success_and_empty_response(self):
        response = make_completion_response()
        client = make_chat_client(response)

        with patch("app.services.ai.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.text_completion.extract_chat_completion_text",
            return_value="  hello world  ",
        ), patch(
            "app.services.ai.llm.text_completion.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            text = await text_completion.generate_text_completion(
                "prompt",
                operation_name="text",
                system_prompt="system",
            )

        self.assertEqual(text, "hello world")
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["messages"][0], {"role": "system", "content": "system"})

        with patch("app.services.ai.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.text_completion.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.ai.llm.text_completion.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            with self.assertRaises(RuntimeError):
                await text_completion.generate_text_completion(
                    "prompt",
                    operation_name="text",
                )

    async def test_generate_text_completion_sends_images_and_falls_back_to_text(self):
        response = make_completion_response()
        client = make_chat_client()
        client.chat.completions.create.side_effect = [RuntimeError("vision unsupported"), response]

        with patch("app.services.ai.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.text_completion.extract_chat_completion_text",
            return_value="answer",
        ), patch(
            "app.services.ai.llm.text_completion.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            result = await text_completion.generate_text_completion(
                "describe the figure",
                operation_name="multimodal",
                image_inputs=[{"image_data": "data:image/png;base64,aW1n"}],
            )

        self.assertEqual(result, "answer")
        first_messages = client.chat.completions.create.call_args_list[0].kwargs["messages"]
        second_messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertIsInstance(first_messages[-1]["content"], list)
        self.assertEqual(first_messages[-1]["content"][-1]["type"], "image_url")
        self.assertEqual(second_messages[-1], {"role": "user", "content": "describe the figure"})

    async def test_generate_text_completion_reraises_text_only_provider_error(self):
        client = make_chat_client()
        client.chat.completions.create.side_effect = RuntimeError("provider down")

        with patch("app.services.ai.llm.text_completion.get_llm_client", return_value=client), patch(
            "app.services.ai.llm.text_completion.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.llm.text_completion.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            with self.assertRaises(RuntimeError):
                await text_completion.generate_text_completion("prompt", operation_name="text")

    def test_build_multimodal_content_deduplicates_and_caps_images(self):
        self.assertEqual(multimodal.build_multimodal_content("text", []), "text")
        images = [
            {"image_data": "data:image/png;base64,0"},
            {"image_data": "data:image/png;base64,0"},
            {},
            {"data_url": "data:image/png;base64,1"},
            *({"image_data": f"data:image/png;base64,{index}"} for index in range(2, 8)),
        ]

        content = multimodal.build_multimodal_content("text", images)

        self.assertEqual(len(content), 7)
        self.assertEqual(content[0], {"type": "text", "text": "text"})
        self.assertEqual(content[-1]["image_url"]["url"], "data:image/png;base64,5")


class QuizFeedbackServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_quiz_feedback_text_success_and_empty_response(self):
        response = make_completion_response()
        client = make_chat_client(response)

        with patch("app.services.ai.quiz_feedback_service.get_default_llm_model_name", return_value="model"), patch(
            "app.services.ai.quiz_feedback_service.get_llm_client",
            return_value=client,
        ), patch(
            "app.services.ai.quiz_feedback_service.extract_chat_completion_text",
            return_value="Nice work",
        ), patch(
            "app.services.ai.quiz_feedback_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
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

        with patch("app.services.ai.quiz_feedback_service.get_default_llm_model_name", return_value="model"), patch(
            "app.services.ai.quiz_feedback_service.get_llm_client",
            return_value=client,
        ), patch(
            "app.services.ai.quiz_feedback_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.ai.quiz_feedback_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            with self.assertRaises(RuntimeError):
                await quiz_feedback_service.generate_quiz_feedback_text("Quiz", 8, 10, 80, [], [])


class ExamAiGradingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_grade_answer_parses_json_and_clamps_marks(self):
        response = make_completion_response()
        client = make_chat_client(response)

        self.assertIn("No specific marking criteria", exam_grading_prompts.format_marking_criteria(None))
        self.assertIn("Reference/Model Answer", exam_grading_prompts.format_reference_answer("It blocks"))
        self.assertEqual(exam_grading_runtime.clamp_marks({"marks_earned": 99}, 3)["marks_earned"], 3)

        wrapped_json = """```json\n{"marks_earned": 99, "feedback": "Good", "is_correct": true, "analysis": "ok"}\n```"""
        with patch("app.services.ai.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value=wrapped_json,
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
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
        response = make_completion_response(choices=False)
        client = make_chat_client(response)

        with patch("app.services.ai.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
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
            "app.services.ai.exam_ai_grading_service.get_llm_client",
            return_value=make_chat_client(make_completion_response()),
        ), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value=wrapped_raw,
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
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
            "app.services.ai.exam_ai_grading_service.get_llm_client",
            return_value=make_chat_client(make_completion_response()),
        ), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value="not-json",
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
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

        with patch("app.services.ai.exam_ai_grading_service.with_llm_retry_async", side_effect=RuntimeError("provider down")):
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
        response = make_completion_response()
        client = make_chat_client(response)

        with patch("app.services.ai.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value="Great effort",
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            comment = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(comment, "Great effort")

        with patch("app.services.ai.exam_ai_grading_service.get_llm_client", return_value=client), patch(
            "app.services.ai.exam_ai_grading_service.get_default_llm_model_name",
            return_value="model",
        ), patch(
            "app.services.ai.exam_ai_grading_service.extract_chat_completion_text",
            return_value="",
        ), patch(
            "app.services.ai.exam_ai_grading_service.with_llm_retry_async",
            side_effect=fake_llm_retry,
        ):
            comment = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(comment, "AI comment generation failed.")

        with patch("app.services.ai.exam_ai_grading_service.with_llm_retry_async", side_effect=RuntimeError("provider down")):
            fallback = await exam_ai_grading_service.ai_generate_exam_overall_comment("summary", 8, 10)
        self.assertEqual(fallback, "AI comment generation failed.")
