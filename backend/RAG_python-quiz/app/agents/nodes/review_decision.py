from typing import Any, Dict, List

from app.agents.schemas import ReviewIssue, ReviewResult


def build_review_result(raw_result: Dict[str, Any]) -> tuple[ReviewResult, Dict[str, Any], List[ReviewIssue]]:
    overall_score = raw_result.get("overall_score", 0)
    is_valid = raw_result.get("is_valid", False)
    decision = raw_result.get("decision", "REWRITE")
    research_goal = raw_result.get("research_goal", "")
    summary = raw_result.get("summary", "")

    issues = [
        ReviewIssue(
            question_id=issue.get("question_id", "unknown"),
            issue_type=issue.get("issue_type", "marking_unclear"),
            description=issue.get("description", ""),
            suggestion=issue.get("suggestion", ""),
        )
        for issue in raw_result.get("issues", [])
    ]
    return (
        ReviewResult(
            is_valid=is_valid,
            overall_score=overall_score,
            issues=issues,
            summary=summary,
        ),
        {
            "overall_score": overall_score,
            "is_valid": is_valid,
            "decision": decision,
            "research_goal": research_goal,
            "summary": summary,
        },
        issues,
    )


def build_rewrite_feedback(overall_score: float, summary: str, issues: List[ReviewIssue]) -> str:
    feedback_parts = [
        f"Review score: {overall_score}/100",
        f"Summary: {summary}",
        "Please regenerate the questions and address these issues:",
    ]
    for issue in issues:
        feedback_parts.append(
            f"- Question {issue.question_id}: {issue.description} | Suggestion: {issue.suggestion}"
        )
    return "\n".join(feedback_parts)
