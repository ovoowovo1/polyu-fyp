from typing import Any, Dict, List

from pydantic import BaseModel


class ReviewIssuePayload(BaseModel):
    question_id: str
    issue_type: str
    description: str
    suggestion: str


class ReviewOutputPayload(BaseModel):
    overall_score: float
    is_valid: bool
    decision: str
    research_goal: str = ""
    summary: str
    issues: List[ReviewIssuePayload]


REVIEWER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["overall_score", "is_valid", "decision", "summary", "issues"],
    "properties": {
        "overall_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": "Overall quality score (0-100)",
        },
        "is_valid": {
            "type": "boolean",
            "description": "Whether the review is passed",
        },
        "decision": {
            "type": "string",
            "enum": ["PASS", "REWRITE", "RESEARCH"],
            "description": "Action to take after review",
        },
        "research_goal": {
            "type": "string",
            "description": "Specific topic to research when decision is RESEARCH",
        },
        "summary": {
            "type": "string",
            "description": "Review summary",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question_id", "issue_type", "description", "suggestion"],
                "properties": {
                    "question_id": {"type": "string"},
                    "issue_type": {
                        "type": "string",
                        "enum": ["context_mismatch", "answer_error", "marking_unclear", "image_issue"],
                    },
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "description": "List of issues found; empty when no problems were found",
        },
    },
    "additionalProperties": False,
}
