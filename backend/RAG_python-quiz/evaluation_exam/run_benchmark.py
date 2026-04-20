#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.utils.api_key_manager import (  # noqa: E402
    with_gemini_retry_async,
    get_genai_client,
    get_default_model_name,
)


CRITERIA_NAMES = [
    "relevance_to_material",
    "coverage",
    "difficulty_alignment",
    "logical_coherence",
    "pedagogical_value",
    "clarity",
    "answerability",
]


def _http_get_json(url: str, token: str | None) -> Dict[str, Any]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
        return json.loads(data)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code} for {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}") from e


def _get_exam(api_base: str, token: str | None, exam_id: str) -> Dict[str, Any]:
    url = f"{api_base.rstrip('/')}/exam/{urllib.parse.quote(exam_id)}?include_answers=true"
    payload = _http_get_json(url, token)
    return payload.get("exam") or payload


def _get_context_from_files(api_base: str, token: str | None, file_ids: List[str]) -> str:
    if not file_ids:
        return ""
    parts: List[str] = []
    for fid in file_ids:
        url = f"{api_base.rstrip('/')}/files/{urllib.parse.quote(fid)}"
        payload = _http_get_json(url, token)
        file_info = payload.get("file") or {}
        chunks = payload.get("chunks") or []
        chunks_sorted = sorted(chunks, key=lambda c: c.get("chunk_index", 0))
        text = "\n".join(c.get("content", "") for c in chunks_sorted if c.get("content"))
        if file_info.get("filename"):
            parts.append(f"\n\n=== {file_info['filename']} ===\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(p for p in parts if p).strip()


def _truncate_text(text: str, max_chars: int) -> Tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = max_chars // 2
    tail = max_chars - head
    trimmed = text[:head] + "\n\n[...TRUNCATED...]\n\n" + text[-tail:]
    return trimmed, True


def _format_questions(questions: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for i, q in enumerate(questions, start=1):
        q_type = q.get("question_type") or "unknown"
        text = q.get("question_text") or q.get("question") or ""
        marks = q.get("marks", "")
        lines.append(f"Q{i} ({q_type}, marks={marks}): {text}")
        if q_type == "multiple_choice":
            choices = q.get("choices") or []
            for idx, choice in enumerate(choices):
                label = chr(65 + idx)
                lines.append(f"  {label}. {choice}")
            if q.get("correct_answer_index") is not None:
                lines.append(f"  correct_answer_index: {q.get('correct_answer_index')}")
        else:
            model_answer = q.get("model_answer")
            if model_answer:
                lines.append(f"  model_answer: {model_answer[:500]}")
            marking = q.get("marking_scheme")
            if marking:
                lines.append(f"  marking_scheme: {json.dumps(marking)[:500]}")
        if q.get("bloom_level"):
            lines.append(f"  bloom_level: {q.get('bloom_level')}")
        if q.get("rationale"):
            lines.append(f"  rationale: {q.get('rationale')[:300]}")
    return "\n".join(lines)


def _build_prompt(exam: Dict[str, Any], questions_block: str, context_text: str) -> str:
    title = exam.get("title") or "Untitled Exam"
    difficulty = exam.get("difficulty") or "unknown"
    num_questions = len(exam.get("questions") or [])
    criteria_desc = (
        "Scoring scale per criterion (0-5):\n"
        "0 = completely fails, 1 = poor, 2 = weak, 3 = acceptable, 4 = strong, 5 = excellent.\n"
    )
    return (
        "You are an impartial exam quality evaluator for a university course.\n"
        "Evaluate the exam strictly based on the provided course material.\n"
        "Do not use outside knowledge. If a question cannot be answered from the material, flag it.\n\n"
        f"{criteria_desc}\n"
        "Criteria definitions:\n"
        "- relevance_to_material: Are questions clearly grounded in the material?\n"
        "- coverage: Do questions cover the key topics of the material broadly?\n"
        "- difficulty_alignment: Is the difficulty consistent with the stated level?\n"
        "- logical_coherence: Do questions follow a logical flow or form a structured assessment of knowledge?\n"
        "- pedagogical_value: Do questions encourage critical thinking, avoid rote memorization, and provide educational value?\n"
        "- clarity: Are questions unambiguous and well-phrased?\n"
        "- answerability: Can a student answer based on the material without guessing?\n\n"
        "Return JSON only. No markdown.\n\n"
        f"Exam title: {title}\n"
        f"Exam difficulty: {difficulty}\n"
        f"Number of questions: {num_questions}\n\n"
        "Course material:\n"
        f"{context_text}\n\n"
        "Exam questions:\n"
        f"{questions_block}\n"
    )


def _evaluation_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "array",
                "minItems": len(CRITERIA_NAMES),
                "maxItems": len(CRITERIA_NAMES),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": CRITERIA_NAMES},
                        "score": {"type": "number"},
                        "evidence": {"type": "string"},
                        "issues": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "score", "evidence", "issues"],
                },
            },
            "unsupported_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_number": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["question_number", "reason"],
                },
            },
            "overall_comment": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "weaknesses": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["criteria", "unsupported_questions", "overall_comment", "strengths", "weaknesses"],
    }


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from model: {e}") from e


async def _run_llm_evaluation(prompt: str) -> Dict[str, Any]:
    schema = _evaluation_schema()
    model_name = get_default_model_name()

    async def _call(api_key: str, prompt: str, schema: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        client = get_genai_client(api_key)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[
                {"role": "system", "content": "Return valid JSON only. No markdown."},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "exam_benchmark",
                    "strict": False,
                    "schema": schema,
                },
            },
            temperature=0.0,
        )
        raw_text = response.choices[0].message.content if response.choices else ""
        return _parse_json(raw_text)

    return await with_gemini_retry_async(
        "Exam Benchmark",
        _call,
        prompt,
        schema,
        model_name,
        error_type=RuntimeError,
    )


def _compute_overall(criteria: List[Dict[str, Any]]) -> int:
    if not criteria:
        return 0
    scores = []
    for item in criteria:
        score = float(item.get("score", 0))
        score = max(0.0, min(5.0, score))
        item["score"] = score
        scores.append(score)
    avg = sum(scores) / (len(scores) * 5.0)
    return int(round(avg * 100))


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM benchmark for a generated exam.")
    parser.add_argument("--exam-id", required=True, help="Exam UUID")
    parser.add_argument("--api-base", default=os.getenv("EVAL_API_BASE", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("EVAL_AUTH_TOKEN"))
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    exam = _get_exam(args.api_base, args.token, args.exam_id)
    questions = exam.get("questions") or []
    file_ids = exam.get("file_ids") or []

    context_text = _get_context_from_files(args.api_base, args.token, file_ids)
    context_text, truncated = _truncate_text(context_text, args.max_context_chars)

    questions_block = _format_questions(questions)
    prompt = _build_prompt(exam, questions_block, context_text)

    result = asyncio.run(_run_llm_evaluation(prompt))
    overall_score = _compute_overall(result.get("criteria") or [])

    report = {
        "exam_id": args.exam_id,
        "exam_title": exam.get("title"),
        "difficulty": exam.get("difficulty"),
        "num_questions": len(questions),
        "file_ids": file_ids,
        "context_chars": len(context_text),
        "context_truncated": truncated,
        "overall_score": overall_score,
        "criteria": result.get("criteria") or [],
        "unsupported_questions": result.get("unsupported_questions") or [],
        "overall_comment": result.get("overall_comment"),
        "strengths": result.get("strengths") or [],
        "weaknesses": result.get("weaknesses") or [],
        "model": get_default_model_name(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    output_path = args.output or os.path.join(
        SCRIPT_DIR, f"report_{args.exam_id}.json"
    )
    _write_json(output_path, report)
    print(f"Saved report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
