from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict
from openai import OpenAI
import os
import json
from pydantic import BaseModel as _BaseModel
from app.utils.pdf_utils import extract_text_by_page
from app.utils.openai_response import extract_chat_completion_text


# ---------- Pydantic schemas for structured output ----------
BloomLevel = Literal[
    "remember", "understand", "apply", "analyze", "evaluate", "create"
]

Difficulty = Literal["easy", "medium", "difficult"]

class MultipleChoice(BaseModel):
    bloom_level: BloomLevel
    question: str
    choices: List[str] = Field(..., min_items=4, max_items=4)
    answer_index: int = Field(..., ge=0, le=3, description="0-based index of correct choice")
    rationale: str = Field(..., description="Short explanation for the correct answer")

class AQGRequest(BaseModel):
    bloom_levels: List[BloomLevel]
    num_questions: int = Field(ge=1, le=50)
    source_text: str
    difficulty: Optional[Difficulty] = None

class _MC(_BaseModel):
    bloom_level: BloomLevel
    question: str
    choices: List[str] = Field(..., min_items=4, max_items=4, description="Exactly 4 choices")
    answer_index: int = Field(..., ge=0, le=3, description="0-based index of correct choice")
    rationale: str

class _QuizWithName(_BaseModel):
    quiz_name: str
    questions: List[_MC]

# ---------- Utilities ----------

MAX_SOURCE_CHARS = 12000  # keep prompts small enough for fast, cheap calls
SUMMARY_TARGET_CHARS = 6000

BLOOM_DESCRIPTIONS: Dict[str, str] = {
    "remember": "assess recall of facts, definitions, terms, and simple properties",
    "understand": "assess comprehension—paraphrase concepts, identify relationships, explain purposes",
    "apply": "assess transfer—apply concepts, formulas, or procedures to new but similar situations",
    "analyze": "assess analysis—compare/contrast, identify causes/effects, parts/whole, assumptions",
    "evaluate": "assess judgments—critique, justify, prioritize using explicit criteria from the text",
    "create": "assess synthesis—design, propose, or assemble a novel solution consistent with the text",
}

DIFFICULTY_TO_BLOOM: Dict[Difficulty, List[BloomLevel]] = {
    "easy": ["remember", "understand"],
    "medium": ["apply", "analyze"],
    "difficult": ["evaluate", "create"],
}

async def read_pdf_to_text(file_bytes: bytes) -> str:
    """Extracts text from a PDF using pdf_utils."""
    try:
        pages = await extract_text_by_page(file_bytes)
        text = "\n\n".join(pages)
        # basic cleanup
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF parse failed: {e}")


def maybe_truncate_or_summarize(client: OpenAI, model: str, text: str) -> str:
    """If text too long, ask the model to summarize into key points before question generation."""
    if len(text) <= MAX_SOURCE_CHARS:
        return text
    # Summarize with strict instructions to preserve terminology and definitions
    prompt = (
        "You are an expert instructional designer. Summarize the following course material into an "
        "exam-writer digest that preserves terminology, definitions, mechanisms, and constraints. "
        "Return concise bullet points; avoid anecdotes and lengthy examples. Keep it under "
        f"{SUMMARY_TARGET_CHARS} characters.\n\nTEXT:\n" + text
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    return extract_chat_completion_text(response, "課程內容摘要")


def distribute_counts(total: int, levels: List[BloomLevel]) -> Dict[BloomLevel, int]:
    """Evenly distribute total across levels; ensure sum equals total and each selected level gets at least 1 if possible."""
    if not levels:
        return {}
    n = len(levels)
    base = total // n
    remainder = total % n
    counts = {lvl: base for lvl in levels}
    # spread the remainder deterministically by order
    for i in range(remainder):
        counts[levels[i]] += 1
    # if total < n, give 1 to first `total` levels
    if total < n:
        counts = {lvl: (1 if i < total else 0) for i, lvl in enumerate(levels)}
    return counts


def build_prompt(source_text: str, level_counts: Dict[BloomLevel, int]) -> str:
    # Build per-level instruction lines and quotas
    level_lines = []
    for lvl, cnt in level_counts.items():
        if cnt <= 0:
            continue
        level_lines.append(f"- {lvl}: {BLOOM_DESCRIPTIONS[lvl]} (generate {cnt} questions)")

    # Guard: if all counts are zero (edge case), fall back to remember with 1
    if not level_lines:
        level_lines = [f"- remember: {BLOOM_DESCRIPTIONS['remember']} (generate 1 question)"]

    # NOTE: We ask the model to respect exact per-level quotas and return only JSON.
    
    return f"""
You are a university-level question writer. Based strictly on the SOURCE TEXT, generate multiple-choice questions across these Bloom levels with the exact quotas specified:
{os.linesep.join(level_lines)}

Global constraints:
- Each question MUST be answerable from the SOURCE TEXT (no outside knowledge).
- Do NOT copy sentences verbatim; paraphrase.
- Provide exactly 4 choices; only one is correct.
- Distractors must be plausible and target common misconceptions.
- Tag each item with its bloom_level from: {list(level_counts.keys())}.
- Provide a short rationale explaining why the correct option is right.

Additionally, generate a concise and descriptive quiz name that reflects the main topic and focus of the quiz based on the source text.

Output Format Requirements:
Please output valid JSON matching the specified schema.

SOURCE TEXT:\n{source_text}
"""
