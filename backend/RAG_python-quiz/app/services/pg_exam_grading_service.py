# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional

from app.services.exceptions import NotFoundError
from app.services.pg_db import _get_conn
from app.services.pg_shared import maybe_iso, stringify_id


def grade_exam_submission(
    submission_id: str,
    teacher_id: str,
    answers_grades: Optional[List[Dict[str, Any]]] = None,
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, total_marks FROM exam_submissions WHERE id = %s", (submission_id,))
        sub = cur.fetchone()
        if not sub:
            raise NotFoundError("Submission not found")

        if answers_grades:
            for g in answers_grades:
                answer_id = g.get("answer_id")
                eq_id = g.get("exam_question_id")

                if answer_id:
                    cur.execute(
                        """
                        UPDATE exam_answers
                        SET marks_earned = %s,
                            teacher_feedback = %s
                        WHERE id = %s
                    """,
                        (
                            g.get("marks_earned", 0),
                            g.get("teacher_feedback"),
                            answer_id,
                        ),
                    )
                elif eq_id:
                    cur.execute(
                        """
                        UPDATE exam_answers
                        SET marks_earned = %s,
                            teacher_feedback = %s
                        WHERE submission_id = %s AND exam_question_id = %s
                    """,
                        (
                            g.get("marks_earned", 0),
                            g.get("teacher_feedback"),
                            submission_id,
                            eq_id,
                        ),
                    )

        cur.execute(
            """
            SELECT COALESCE(SUM(marks_earned), 0) AS total_score
            FROM exam_answers
            WHERE submission_id = %s
        """,
            (submission_id,),
        )
        score = cur.fetchone()["total_score"]

        cur.execute(
            """
            UPDATE exam_submissions
            SET score = %s,
                teacher_comment = COALESCE(%s, teacher_comment),
                graded_by = %s,
                graded_at = now(),
                grading_source = 'teacher',
                status = 'graded'
            WHERE id = %s
            RETURNING id, score, graded_at
        """,
            (
                score,
                teacher_comment,
                teacher_id,
                submission_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        return {
            "submission_id": str(row["id"]),
            "score": row["score"],
            "total_marks": sub["total_marks"],
            "graded_at": maybe_iso(row["graded_at"]),
            "status": "graded",
        }


def ai_grade_exam_submission(
    submission_id: str,
    graded_answers: List[Dict[str, Any]],
    teacher_comment: Optional[str] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, total_marks FROM exam_submissions WHERE id = %s
        """,
            (submission_id,),
        )
        sub = cur.fetchone()
        if not sub:
            raise NotFoundError("Submission not found")

        for g in graded_answers:
            answer_id = g.get("answer_id")
            eq_id = g.get("exam_question_id")

            if answer_id:
                cur.execute(
                    """
                    UPDATE exam_answers
                    SET marks_earned = %s,
                        teacher_feedback = %s,
                        is_correct = %s
                    WHERE id = %s
                """,
                    (
                        g.get("marks_earned", 0),
                        g.get("teacher_feedback"),
                        g.get("is_correct", False),
                        answer_id,
                    ),
                )
            elif eq_id:
                cur.execute(
                    """
                    UPDATE exam_answers
                    SET marks_earned = %s,
                        teacher_feedback = %s,
                        is_correct = %s
                    WHERE submission_id = %s AND exam_question_id = %s
                """,
                    (
                        g.get("marks_earned", 0),
                        g.get("teacher_feedback"),
                        g.get("is_correct", False),
                        submission_id,
                        eq_id,
                    ),
                )

        cur.execute(
            """
            SELECT COALESCE(SUM(marks_earned), 0) AS total_score
            FROM exam_answers
            WHERE submission_id = %s
        """,
            (submission_id,),
        )
        score = cur.fetchone()["total_score"]

        if teacher_comment:
            cur.execute(
                """
                UPDATE exam_submissions
                SET score = %s,
                    graded_at = now(),
                    graded_by = NULL,
                    grading_source = 'ai',
                    status = 'ai_graded',
                    teacher_comment = %s
                WHERE id = %s
                RETURNING id, score, graded_at, status, teacher_comment
            """,
                (score, teacher_comment, submission_id),
            )
        else:
            cur.execute(
                """
                UPDATE exam_submissions
                SET score = %s,
                    graded_at = now(),
                    graded_by = NULL,
                    grading_source = 'ai',
                    status = 'ai_graded'
                WHERE id = %s
                RETURNING id, score, graded_at, status, teacher_comment
            """,
                (score, submission_id),
            )

        row = cur.fetchone()
        conn.commit()

        return {
            "submission_id": stringify_id(row["id"]),
            "score": row["score"],
            "total_marks": sub["total_marks"],
            "graded_at": maybe_iso(row["graded_at"]),
            "status": row["status"],
            "grading_source": "ai",
            "teacher_comment": row.get("teacher_comment"),
        }



__all__ = [
    "ai_grade_exam_submission",
    "grade_exam_submission",
]
