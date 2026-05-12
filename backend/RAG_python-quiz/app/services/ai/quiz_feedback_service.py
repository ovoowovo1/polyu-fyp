from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text


_BLOOM_FRIENDLY_LABELS = {
    "remember": "基礎記憶/重點回憶",
    "understand": "理解概念",
    "apply": "應用題",
    "analyze": "分析比較",
    "evaluate": "評估判斷",
    "create": "設計/創作",
    "general": "綜合表現",
}


def _format_bloom_summary(bloom_summary: List[Dict[str, Any]]) -> str:
    return "\n".join(
        [
            f"- {_BLOOM_FRIENDLY_LABELS.get(b.get('level', 'general'), '綜合表現')}: "
            f"{b.get('correct', 0)}/{b.get('total', 0)} ({b.get('accuracy', 0)}%)"
            for b in (bloom_summary or [])
        ]
    ) or "無分項統計"


def _format_question_snapshots(questions: List[Dict[str, Any]]) -> str:
    question_lines = []
    for question in questions or []:
        user_answer_index = question.get("user_answer_index")
        correct_answer_index = question.get("correct_answer_index")
        question_lines.append(
            f"Q: {question.get('question', '')}\n"
            f"Your answer index: {user_answer_index}, "
            f"Correct index: {correct_answer_index}, "
            f"Bloom: {question.get('bloom_level', 'general')}"
        )
    return "\n\n".join(question_lines) or "No question details."


def _build_quiz_feedback_prompt(
    quiz_name: str,
    score: int,
    total: int,
    percentage: int,
    bloom_summary: List[Dict[str, Any]],
    questions: List[Dict[str, Any]],
) -> str:
    return (
        "You are a friendly tutor. Provide concise encouragement and specific study advice.\n"
        "Keep it to 2-3 sentences total. Tone: supportive, specific.\n"
        "Cover briefly: 1) Praise & overall performance; 2) Weak areas "
        "(describe with plain language, avoid jargon like Bloom labels); 3) 2-3 actionable tips.\n"
        "Avoid per-question overlong analysis; do not list all options.\n\n"
        f"Quiz name: {quiz_name or 'Quiz'}\n"
        f"Score: {score}/{total} ({percentage}%)\n"
        "Bloom summary:\n"
        f"{_format_bloom_summary(bloom_summary)}\n\n"
        "Question snapshots (indices only):\n"
        f"{_format_question_snapshots(questions)}\n"
    )


async def generate_quiz_feedback_text(
    quiz_name: str,
    score: int,
    total: int,
    percentage: int,
    bloom_summary: List[Dict[str, Any]],
    questions: List[Dict[str, Any]],
    *,
    operation_name: str = "AI 測驗回饋生成",
) -> str:
    prompt = _build_quiz_feedback_prompt(
        quiz_name,
        score,
        total,
        percentage,
        bloom_summary,
        questions,
    )
    model_name = get_default_llm_model_name()

    async def _generate_feedback(api_key: str, prompt: str, model_name: str) -> str:
        client = get_llm_client(api_key)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        text = extract_chat_completion_text(response, operation_name)
        if not text:
            raise RuntimeError("Empty feedback response from model")
        return text

    return await with_llm_retry_async(
        operation_name,
        _generate_feedback,
        prompt,
        model_name,
        error_type=RuntimeError,
    )
