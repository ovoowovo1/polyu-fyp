from typing import Any, Dict, List, Optional
import asyncio

from app.utils.api_key_manager import with_llm_retry_async, get_llm_client, get_default_llm_model_name
from app.utils.openai_response import extract_chat_completion_text
from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)


def _parse_structured_json_text(text: str, operation_name: str) -> Dict[str, Any]:
    import json
    import re

    raw = (text or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"{operation_name} returned invalid JSON: {raw[:200]}") from err

    if not isinstance(parsed, dict):
        raise RuntimeError(f"{operation_name} returned JSON that is not an object")
    return parsed


def _validate_structured_json_result(result: Dict[str, Any], schema: Dict[str, Any], operation_name: str) -> None:
    missing = [field for field in schema.get("required", []) if field not in result]
    if missing:
        raise RuntimeError(f"{operation_name} returned JSON missing required fields: {missing}")


def _prefers_plain_json_response(model_name: str) -> bool:
    return (model_name or "").lower().startswith("deepseek/")


def _plain_json_system_prompt(schema: Dict[str, Any], system_prompt: Optional[str]) -> str:
    import json

    prefix = f"{system_prompt.strip()}\n\n" if system_prompt else ""
    return f"{prefix}Return only valid JSON matching this schema. Do not include markdown, comments, or extra text.\nSchema:\n{json.dumps(schema)}"


async def generate_structured_json(
    prompt: str,
    schema: Dict[str, Any],
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    async def _generate(api_key: str) -> Dict[str, Any]:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()

        async def _call_model(*, response_format_mode: str, fallback_mode: str) -> Dict[str, Any]:
            if response_format_mode == "plain_json":
                messages = [
                    {"role": "system", "content": _plain_json_system_prompt(schema, system_prompt)},
                    {"role": "user", "content": prompt},
                ]
                kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": temperature,
                }
            else:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                kwargs = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": temperature,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "structured_response",
                            "strict": False,
                            "schema": schema,
                        },
                    },
                }

            logger.info(
                "[%s] structured_json request model=%s response_format_mode=%s fallback_mode=%s",
                operation_name,
                model_name,
                response_format_mode,
                fallback_mode,
            )
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
            text = extract_chat_completion_text(response, operation_name)
            if not text:
                raise RuntimeError(f"{operation_name} returned empty content")
            result = _parse_structured_json_text(text, operation_name)
            _validate_structured_json_result(result, schema, operation_name)
            return result

        if _prefers_plain_json_response(model_name):
            try:
                return await _call_model(response_format_mode="plain_json", fallback_mode="preferred")
            except Exception as err:
                logger.error(
                    "[%s] structured_json plain JSON request failed model=%s: %s",
                    operation_name,
                    model_name,
                    err,
                )
                raise

        try:
            return await _call_model(response_format_mode="json_schema", fallback_mode="available")
        except Exception as first_err:
            logger.warning(
                "[%s] structured_json json_schema request failed model=%s; retrying once with plain JSON fallback: %s",
                operation_name,
                model_name,
                first_err,
            )
            try:
                return await _call_model(response_format_mode="plain_json", fallback_mode="retry_after_json_schema_failure")
            except Exception as fallback_err:
                logger.error(
                    "[%s] structured_json plain JSON fallback failed model=%s after json_schema error=%s fallback_error=%s",
                    operation_name,
                    model_name,
                    first_err,
                    fallback_err,
                )
                raise RuntimeError(f"{operation_name} failed after plain JSON fallback: {fallback_err}") from fallback_err

    return await with_llm_retry_async(
        operation_name,
        _generate,
        error_type=RuntimeError,
    )


async def generate_text_completion(
    prompt: str,
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> str:
    async def _generate(api_key: str) -> str:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=messages,
            temperature=temperature,
        )
        text = extract_chat_completion_text(response, operation_name)
        if not text:
            raise RuntimeError(f"{operation_name} returned empty content")
        return text.strip()

    return await with_llm_retry_async(
        operation_name,
        _generate,
        error_type=RuntimeError,
    )



async def generate_quiz_feedback_text(
    quiz_name: str,
    score: int,
    total: int,
    percentage: int,
    bloom_summary: List[Dict[str, Any]],
    questions: List[Dict[str, Any]],
    *,
    operation_name: str = "AI 測驗回饋生成"
) -> str:
    """
    生成 AI 測驗回饋的自由文本，統一使用 with_llm_retry_async 管理 key 輪替與重試。
    """
    settings = get_settings()
    model_name = settings.llm_model or "gemini-2.5-flash"

    # 將 Bloom 標籤轉為更易懂的描述，避免直接暴露術語
    bloom_friendly = {
        "remember": "基礎記憶/重點回憶",
        "understand": "理解概念",
        "apply": "應用題",
        "analyze": "分析比較",
        "evaluate": "評估判斷",
        "create": "設計/創作",
        "general": "綜合表現",
    }
    bloom_lines = "\n".join(
        [
            f"- {bloom_friendly.get(b.get('level', 'general'), '綜合表現')}: "
            f"{b.get('correct', 0)}/{b.get('total', 0)} ({b.get('accuracy', 0)}%)"
            for b in (bloom_summary or [])
        ]
    ) or "無分項統計"

    question_lines = []
    for q in (questions or []):
        ua = q.get("user_answer_index")
        ca = q.get("correct_answer_index")
        question_lines.append(
            f"Q: {q.get('question','')}\n"
            f"Your answer index: {ua}, Correct index: {ca}, Bloom: {q.get('bloom_level','general')}"
        )
    question_block = "\n\n".join(question_lines) or "No question details."

    prompt = (
        "You are a friendly tutor. Provide concise encouragement and specific study advice.\n"
        "Keep it to 2-3 sentences total. Tone: supportive, specific.\n"
        "Cover briefly: 1) Praise & overall performance; 2) Weak areas (describe with plain language, avoid jargon like Bloom labels); 3) 2-3 actionable tips.\n"
        "Avoid per-question overlong analysis; do not list all options.\n\n"
        f"Quiz name: {quiz_name or 'Quiz'}\n"
        f"Score: {score}/{total} ({percentage}%)\n"
        "Bloom summary:\n"
        f"{bloom_lines}\n\n"
        "Question snapshots (indices only):\n"
        f"{question_block}\n"
    )

    async def _generate_feedback(api_key: str, prompt: str, model_name: str) -> str:
        client = get_llm_client(api_key)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[{"role": "user", "content": prompt}]
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
        error_type=RuntimeError
    )


async def ai_grade_answer(
    question_text: str,
    question_type: str,
    model_answer: Optional[str],
    marking_scheme: Optional[List[Dict[str, Any]]],
    student_answer: str,
    max_marks: int,
    *,
    operation_name: str = "AI Exam Grading"
) -> Dict[str, Any]:
    """
    Use Gemini to grade a short answer/essay question.
    
    Returns:
        {
            "marks_earned": int,
            "feedback": str,
            "is_correct": bool,
            "analysis": str
        }
    """
    # Build the grading schema for structured output
    # Note: Using format compatible with Gemini's response_schema
    schema = {
        "type": "object",
        "properties": {
            "marks_earned": {
                "type": "number"  # Gemini prefers "number" over "integer"
            },
            "feedback": {
                "type": "string"
            },
            "is_correct": {
                "type": "boolean"
            },
            "analysis": {
                "type": "string"
            }
        },
        "required": ["marks_earned", "feedback", "is_correct", "analysis"]
    }
    
    # Build marking criteria description
    criteria_text = ""
    if marking_scheme and len(marking_scheme) > 0:
        criteria_lines = []
        for m in marking_scheme:
            criteria_lines.append(f"- {m.get('criterion', 'Criterion')}: {m.get('marks', 0)} marks")
        criteria_text = "\n".join(criteria_lines)
    else:
        criteria_text = "No specific marking criteria provided. Use your knowledge to evaluate the answer."
    
    # Build model answer description
    reference_text = ""
    if model_answer:
        reference_text = f"Reference/Model Answer:\n{model_answer}"
    else:
        reference_text = "No model answer provided. Use your knowledge to evaluate correctness based on the question."
    
    prompt = f"""
    
You are an objective and expert exam grader. 

**Task**: Grade the student's answer based on the provided criteria.

**Question**: {question_text}
**Maximum Marks**: {max_marks}

**Marking Criteria**:
{criteria_text}

{reference_text}

**Student's Answer**:
{student_answer if student_answer else "(No answer provided)"}

**Grading Philosophy**:
1. **Prioritize Substance**: If the student's answer addresses the core requirements of the marking criteria, award full marks, even if they use different terminology or are very concise.
2. **Partial Credit**: Be generous with partial marks if a portion of the criteria is met.
3. **Reasoning First**: Analyze the answer against each criterion before deciding the final score.

**Instructions**:
- Provide feedback in 2-3 sentences max.
- Feedback should tell the student exactly what they missed (if any).
- Respond in English.

**Response Format**:
You MUST respond with valid JSON using this schema:
{{
  "analysis": "Step-by-step evaluation of the answer against the criteria",
  "marks_earned": <number>,
  "feedback": "Brief explanation",
  "is_correct": <boolean, true only if marks_earned == {max_marks}>
}}

"""

    # Log input data for debugging
    logger.info(f"[AI Grading] === Input Debug ===")
    logger.info(f"[AI Grading] question_type: {question_type}")
    logger.info(f"[AI Grading] question_text: {question_text[:100] if question_text else 'EMPTY'}...")
    logger.info(f"[AI Grading] student_answer: '{student_answer}' (len={len(student_answer) if student_answer else 0})")
    logger.info(f"[AI Grading] max_marks: {max_marks}")
    logger.info(f"[AI Grading] model_answer: {model_answer[:100] if model_answer else 'None'}...")
    logger.info(f"[AI Grading] marking_scheme: {marking_scheme}")
    logger.info(f"[AI Grading] Full prompt length: {len(prompt)} chars")

    async def _grade_answer(api_key: str, schema: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """Grade answer using OpenRouter (OpenAI-compatible API)"""
        import json
        
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        
        logger.info(f"[AI Grading] Calling Gemini model via OpenRouter: {model_name}")
        
        # Build system prompt for JSON output
        system_prompt = f"""You are a grading assistant. You MUST respond with valid JSON only, no markdown formatting.
The JSON must match this schema: {json.dumps(schema)}"""
        
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # Deterministic output for the same inputs
                seed=0,
                response_format={"type": "json_object"}
            )
        )
        
        # Log response details
        logger.info(f"[AI Grading] Response object type: {type(response)}")
        
        # Check choices
        if hasattr(response, 'choices') and response.choices:
            logger.info(f"[AI Grading] Choices: {len(response.choices)}")
            for i, c in enumerate(response.choices):
                finish = getattr(c, 'finish_reason', 'N/A')
                logger.info(f"[AI Grading] Choice {i} finish_reason: {finish}")
        else:
            logger.warning(f"[AI Grading] No choices in response!")
        
        text = extract_chat_completion_text(response, operation_name)
        logger.info(f"[AI Grading] Response text: {text[:500] if text else 'EMPTY/None'}")
        
        if not text:
            logger.error(f"[AI Grading] Full response object: {response}")
            raise RuntimeError("Empty response from grading model")
        
        # Try to parse JSON - handle case where model returns markdown-wrapped JSON
        try:
            # First try direct JSON parse
            result = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                # Try to find raw JSON object in the text
                json_match = re.search(r'\{[^{}]*"marks_earned"[^{}]*\}', text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    logger.error(f"[AI Grading] Could not parse JSON from response: {text}")
                    raise RuntimeError(f"Could not parse JSON from response: {text[:200]}")
        
        logger.info(f"[AI Grading] Parsed result: {result}")
        
        # Validate marks_earned is within bounds
        marks = result.get("marks_earned", 0)
        if marks < 0:
            result["marks_earned"] = 0
        elif marks > max_marks:
            result["marks_earned"] = max_marks
            
        return result
    
    try:
        response = await with_llm_retry_async(
            operation_name,
            _grade_answer,
            schema,
            prompt,
            error_type=RuntimeError
        )
        return response
    except Exception as e:
        logger.error(f"AI grading failed: {e}")
        # Return a default response on failure
        return {
            "marks_earned": 0,
            "feedback": f"AI grading failed: {str(e)}. Please grade manually.",
            "is_correct": False
        }


async def ai_generate_exam_overall_comment(
    submission_summary: str,
    total_score: int,
    total_marks: int,
    *,
    operation_name: str = "AI Exam Overall Comment"
) -> str:
    """
    Generate an overall comment for the exam submission.
    """
    prompt = f"""You are an encouraging teacher grading an exam.
    
Student's Total Score: {total_score} / {total_marks}

Question Performance Summary:
{submission_summary}

**Task**: Write an overall comment for this student (approx. 3-5 sentences).

**Structure**:
1. **Praise**: Start by explicitly praising what the student did well (e.g., "You demonstrated a strong understanding of...").
2. **Improvement**: Then, gently explain the main areas that need improvement based on their mistakes (e.g., "However, you should review...").
3. **Encouragement**: End with a professional and supportive closing.

**Tone**: Professional, supportive, constructive.
**Language**: English only.

Write the comment now."""

    async def _generate_comment(api_key: str, prompt: str) -> str:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are an encouraging teacher providing feedback on exam performance."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
            )
        )
        
        text = extract_chat_completion_text(response, operation_name)
        if not text:
            raise RuntimeError("Empty response from model")
        return text

    try:
        return await with_llm_retry_async(
            operation_name,
            _generate_comment,
            prompt,
            error_type=RuntimeError
        )
    except Exception as e:
        logger.error(f"AI overall comment failed: {e}")
        return "AI comment generation failed."
