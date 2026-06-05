from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Literal
from openai import OpenAI
import os

from app.utils.openai_response import extract_chat_completion_text


# ---------- Pydantic schemas for structured output ----------
BloomLevel = Literal[
    "remember", "understand", "apply", "analyze", "evaluate", "create"
]

Difficulty = Literal["easy", "medium", "difficult"]

class MultipleChoice(BaseModel):
    bloom_level: BloomLevel
    question: str
    choices: List[str] = Field(..., min_length=4, max_length=4)
    answer_index: int = Field(..., ge=0, le=3, description="0-based index of correct choice")
    rationale: str = Field(..., description="Short explanation for the correct answer")

class _QuizWithName(BaseModel):
    quiz_name: str
    questions: List[MultipleChoice]

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
    if total < n:
        return {lvl: (1 if i < total else 0) for i, lvl in enumerate(levels)}

    base = total // n
    remainder = total % n
    return {lvl: base + (1 if i < remainder else 0) for i, lvl in enumerate(levels)}


def build_prompt(source_text: str, level_counts: Dict[BloomLevel, int]) -> str:
    # Build per-level instruction lines and quotas
    level_lines = [
        f"- {lvl}: {BLOOM_DESCRIPTIONS[lvl]} (generate {cnt} questions)"
        for lvl, cnt in level_counts.items()
        if cnt > 0
    ]

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
