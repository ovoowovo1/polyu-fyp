from __future__ import annotations

from typing import Dict, List

from app.agents.schemas import BloomLevel

SECTION_ORDER = ["multiple_choice", "short_answer", "essay"]
SECTION_TO_ARRAY = {
    "multiple_choice": "multiple_choice_questions",
    "short_answer": "short_answer_questions",
    "essay": "essay_questions",
}
DEFAULT_MARKS = {"multiple_choice": 1, "short_answer": 3, "essay": 5}

SECTION_CONFIG = {
    "multiple_choice": {
        "label": "Multiple Choice",
        "required_bloom": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `multiple_choice_questions`.",
            "`choices` must contain exactly 4 non-empty strings.",
            "`correct_answer_index` must be an integer from 0 to 3.",
            "Distractors must be plausible and tied to common misconceptions.",
            "Do not include `marks` or `marking_criteria`; the system assigns 1 mark automatically.",
        ],
    },
    "short_answer": {
        "label": "Short Answer",
        "required_bloom": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `short_answer_questions`.",
            "`model_answer` must be 50-150 words.",
            "`marking_criteria` should be an array of rubric objects with `criterion`, `explanation`, and optional `marks`.",
            "Each rubric explanation must briefly state what the student must demonstrate to earn the mark(s).",
            "Questions should test understanding or application, not pure recall only.",
            "Do not include `marks`; the system assigns 3 marks automatically.",
        ],
    },
    "essay": {
        "label": "Essay",
        "required_bloom": ["understand", "apply", "analyze", "evaluate", "create"],
        "question_specific_rules": [
            "Each item must be a JSON object inside `essay_questions`.",
            "`model_answer` must be 200-500 words.",
            "`marking_criteria` should be an array of rubric objects with `criterion`, `explanation`, and optional `marks`.",
            "Each rubric explanation must briefly state what the student must demonstrate to earn the mark(s).",
            "Questions should emphasize analysis, evaluation, or synthesis.",
            "Do not include `marks`; the system assigns 5 marks automatically.",
        ],
    },
}

BLOOM_DESCRIPTIONS = {
    "remember": "Basic Recall - Test memory of facts, definitions, terms",
    "understand": "Understanding - Test comprehension of concepts, ability to explain in own words",
    "apply": "Application - Test ability to apply concepts to new situations",
    "analyze": "Analysis - Test ability to compare, contrast, find causal relationships",
    "evaluate": "Evaluation - Test ability to judge, critique, argue",
    "create": "Creation - Test ability to design, propose new solutions",
}

DIFFICULTY_TO_BLOOM: Dict[str, List[BloomLevel]] = {
    "easy": ["remember", "understand"],
    "medium": ["understand", "apply", "analyze"],
    "difficult": ["analyze", "evaluate", "create"],
}
