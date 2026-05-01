# -*- coding: utf-8 -*-
from datetime import datetime
import json as json_lib
from typing import Any, Dict, List, Optional

from app.services.exceptions import (
    AlreadySubmittedError,
    NotFoundError,
    NotReleasedError,
    PermissionDeniedError,
)
from app.services.pg_db import _get_conn
from app.services.pg_shared import (
    fetch_default_document_names,
    fetch_linked_documents,
    insert_submission_with_attempt,
    linked_document_ids,
    map_exam_answer_row,
    map_exam_submission_row,
    maybe_iso,
    maybe_json_load,
    replace_linked_documents,
    stringify_id,
    stringify_id_list,
)


def _default_exam_title(cur, file_ids: List[str]) -> str:
    """生成預設考試標題"""
    names = fetch_default_document_names(cur, file_ids)
    if len(names) == 1:
        base = names[0].rsplit(".", 1)[0]
        prefix = f"{base} - 考試"
    elif len(names) > 1:
        prefix = f"{len(names)} 個文件的考試"
    else:
        prefix = "考試"
    now = datetime.now()
    return f"{prefix} ({now.strftime('%m/%d %H:%M')})"


def _fetch_exam_answers_map(cur, submission_ids: List[str], *, include_attachments: bool = False):
    if not submission_ids:
        return {}

    attachment_select = ", ea.attachments" if include_attachments else ""
    cur.execute(
        f"""
        SELECT ea.submission_id, ea.id, ea.exam_question_id, ea.question_snapshot,
               ea.answer_text, ea.selected_options, ea.time_spent_seconds,
               ea.is_correct, ea.marks_earned, ea.teacher_feedback{attachment_select}
        FROM exam_answers ea
        JOIN exam_questions eq ON ea.exam_question_id = eq.id
        WHERE ea.submission_id = ANY(%s::uuid[])
        ORDER BY eq.position ASC
        """,
        (submission_ids,),
    )

    answers_map = {}
    for row in cur.fetchall():
        submission_value = row.get("submission_id")
        if submission_value is None and len(submission_ids) == 1:
            submission_value = submission_ids[0]
        submission_key = stringify_id(submission_value)
        answers_map.setdefault(submission_key, []).append(
            map_exam_answer_row(row, include_attachments=include_attachments)
        )
    return answers_map


def save_exam(
    exam_id: str,
    exam_name: str,
    questions: List[Dict[str, Any]],
    file_ids: List[str],
    class_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    difficulty: str = "medium",
    duration_minutes: Optional[int] = None,
    pdf_path: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    total_marks = sum(q.get("marks", 1) for q in questions)

    with _get_conn() as conn, conn.cursor() as cur:
        title = exam_name or _default_exam_title(cur, file_ids)
        cur.execute(
            """
            INSERT INTO exams (id, title, description, questions_json, difficulty, total_marks,
                              duration_minutes, class_id, owner_id, pdf_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                questions_json = EXCLUDED.questions_json,
                difficulty = EXCLUDED.difficulty,
                total_marks = EXCLUDED.total_marks,
                duration_minutes = EXCLUDED.duration_minutes,
                pdf_path = EXCLUDED.pdf_path,
                updated_at = now()
            RETURNING id, created_at
        """,
            (
                exam_id,
                title,
                description,
                json_lib.dumps(questions),
                difficulty,
                total_marks,
                duration_minutes,
                class_id,
                owner_id,
                pdf_path,
            ),
        )
        row = cur.fetchone()

        cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
        for idx, q in enumerate(questions):
            cur.execute(
                """
                INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                VALUES (%s, %s, %s, %s)
            """,
                (
                    exam_id,
                    idx,
                    json_lib.dumps(q),
                    q.get("marks", 1),
                ),
            )

        replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)

        conn.commit()

        return {
            "exam_id": str(row["id"]),
            "title": title,
            "created_at": maybe_iso(row["created_at"]),
            "num_questions": len(questions),
            "total_marks": total_marks,
        }


def get_exams_by_class(class_id: str) -> List[Dict[str, Any]]:
    sql = """
    SELECT e.id, e.title, e.description, e.difficulty, e.total_marks, e.duration_minutes,
           e.created_at, e.updated_at, e.is_published, e.pdf_path, e.owner_id,
           e.start_at, e.end_at,
           (SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS num_questions,
           ARRAY_AGG(DISTINCT ed.document_id)::uuid[] AS file_ids
    FROM exams e
    LEFT JOIN exam_documents ed ON ed.exam_id = e.id
    WHERE e.class_id = %s
    GROUP BY e.id
    ORDER BY e.created_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (class_id,))
        rows = cur.fetchall() or []

        exam_ids = [r["id"] for r in rows]
        docs = fetch_linked_documents(cur, "exam_documents", "exam_id", exam_ids)

        return [
            {
                "id": stringify_id(r["id"]),
                "title": r["title"] or "未命名考試",
                "description": r["description"],
                "difficulty": r["difficulty"],
                "total_marks": r["total_marks"],
                "duration_minutes": r["duration_minutes"],
                "num_questions": r["num_questions"] or 0,
                "created_at": maybe_iso(r["created_at"]),
                "updated_at": maybe_iso(r["updated_at"]),
                "is_published": r["is_published"],
                "start_at": maybe_iso(r["start_at"]),
                "end_at": maybe_iso(r["end_at"]),
                "pdf_path": r["pdf_path"],
                "owner_id": stringify_id(r["owner_id"]),
                "file_ids": stringify_id_list(r["file_ids"]),
                "documents": docs.get(stringify_id(r["id"]), []),
            }
            for r in rows
        ]


def get_exam_by_id(
    exam_id: str, user_id: Optional[str] = None, include_answers: bool = True
) -> Dict[str, Any]:
    sql = """
    SELECT id, title, description, questions_json, difficulty, total_marks, duration_minutes,
           class_id, owner_id, created_at, updated_at, is_published, pdf_path, start_at, end_at
    FROM exams WHERE id = %s
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id,))
        r = cur.fetchone()
        if not r:
            raise NotFoundError("Exam not found")

        documents = fetch_linked_documents(
            cur,
            "exam_documents",
            "exam_id",
            [exam_id],
            include_class_id=True,
        ).get(exam_id, [])

        cur.execute(
            """
            SELECT id, position, question_snapshot, max_marks
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY position ASC
        """,
            (exam_id,),
        )
        eq_rows = cur.fetchall()

        if user_id:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            role = row["role"] if row else None

            if role == "student":
                if not r["is_published"]:
                    raise NotReleasedError()
                if r["class_id"]:
                    cur.execute(
                        "SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s",
                        (r["class_id"], user_id),
                    )
                    if not cur.fetchone():
                        raise PermissionDeniedError("Permission denied")

        if eq_rows:
            questions = []
            for eq in eq_rows:
                q_snapshot = maybe_json_load(eq["question_snapshot"], None)
                q_snapshot["exam_question_id"] = stringify_id(eq["id"])
                questions.append(q_snapshot)
        else:
            questions = maybe_json_load(r["questions_json"], [])

        if not include_answers:
            for q in questions:
                q.pop("correct_answer_index", None)
                q.pop("model_answer", None)
                q.pop("marking_scheme", None)
                q.pop("rationale", None)

        return {
            "id": stringify_id(r["id"]),
            "title": r["title"] or "未命名考試",
            "description": r["description"],
            "questions": questions,
            "difficulty": r["difficulty"],
            "total_marks": r["total_marks"],
            "duration_minutes": r["duration_minutes"],
            "num_questions": len(questions),
            "class_id": stringify_id(r["class_id"]),
            "owner_id": stringify_id(r["owner_id"]),
            "created_at": maybe_iso(r["created_at"]),
            "updated_at": maybe_iso(r["updated_at"]),
            "is_published": r["is_published"],
            "start_at": maybe_iso(r["start_at"]),
            "end_at": maybe_iso(r["end_at"]),
            "pdf_path": r["pdf_path"],
            "file_ids": linked_document_ids(documents),
            "documents": [
                {"id": document["id"], "name": document["name"]}
                for document in documents
            ],
        }


def update_exam(
    exam_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    questions: Optional[List[Dict[str, Any]]] = None,
    difficulty: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    file_ids: Optional[List[str]] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, questions_json FROM exams WHERE id = %s", (exam_id,))
        existing = cur.fetchone()
        if not existing:
            raise NotFoundError("Exam not found")

        updates = ["updated_at = now()"]
        params = []

        if title is not None:
            updates.append("title = %s")
            params.append(title)

        if description is not None:
            updates.append("description = %s")
            params.append(description)

        if questions is not None:
            updates.append("questions_json = %s")
            params.append(json_lib.dumps(questions))
            total_marks = sum(q.get("marks", 1) for q in questions)
            updates.append("total_marks = %s")
            params.append(total_marks)

        if difficulty is not None:
            updates.append("difficulty = %s")
            params.append(difficulty)

        if duration_minutes is not None:
            updates.append("duration_minutes = %s")
            params.append(duration_minutes if duration_minutes > 0 else None)

        if start_at is not None:
            updates.append("start_at = %s")
            params.append(start_at if start_at else None)

        if end_at is not None:
            updates.append("end_at = %s")
            params.append(end_at if end_at else None)

        params.append(exam_id)
        cur.execute(
            f"UPDATE exams SET {', '.join(updates)} WHERE id = %s RETURNING id, title, total_marks",
            params,
        )
        row = cur.fetchone()

        if questions is not None:
            cur.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
            for idx, q in enumerate(questions):
                cur.execute(
                    """
                    INSERT INTO exam_questions (exam_id, position, question_snapshot, max_marks)
                    VALUES (%s, %s, %s, %s)
                """,
                    (
                        exam_id,
                        idx,
                        json_lib.dumps(q),
                        q.get("marks", 1),
                    ),
                )

        if file_ids is not None:
            replace_linked_documents(cur, "exam_documents", "exam_id", exam_id, file_ids)

        conn.commit()

        return {
            "exam_id": stringify_id(row["id"]),
            "title": row["title"],
            "total_marks": row["total_marks"],
        }


def delete_exam(exam_id: str) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM exams WHERE id = %s RETURNING id, title", (exam_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError("Exam not found")
        conn.commit()
        return {"message": "考試已成功刪除", "exam_id": str(row["id"]), "title": row["title"]}


def publish_exam(exam_id: str, is_published: bool = True) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE exams SET is_published = %s, updated_at = now() WHERE id = %s RETURNING id, title, is_published",
            (is_published, exam_id),
        )
        row = cur.fetchone()
        if not row:
            raise NotFoundError("Exam not found")
        conn.commit()
        return {
            "exam_id": str(row["id"]),
            "title": row["title"],
            "is_published": row["is_published"],
        }


def start_exam_submission(
    exam_id: str, student_id: str, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, is_published, duration_minutes, start_at, end_at FROM exams WHERE id = %s",
            (exam_id,),
        )
        exam = cur.fetchone()
        if not exam:
            raise NotFoundError("Exam not found")
        if not exam["is_published"]:
            raise NotReleasedError()

        row, _attempt_no = insert_submission_with_attempt(
            cur,
            "exam_submissions",
            {"exam_id": exam_id, "student_id": student_id},
            """
            INSERT INTO exam_submissions (exam_id, student_id, attempt_no, status, meta)
            VALUES (%s, %s, %s, 'in_progress', %s)
            RETURNING id, started_at, attempt_no
        """,
            lambda attempt_no: (
                exam_id,
                student_id,
                attempt_no,
                json_lib.dumps(meta or {}),
            ),
        )
        conn.commit()

        return {
            "submission_id": stringify_id(row["id"]),
            "started_at": maybe_iso(row["started_at"]),
            "attempt_no": row["attempt_no"],
            "duration_minutes": exam["duration_minutes"],
        }


def submit_exam(
    submission_id: str,
    answers: List[Dict[str, Any]],
    time_spent_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT es.id, es.exam_id, es.status, e.questions_json, e.total_marks
            FROM exam_submissions es
            JOIN exams e ON e.id = es.exam_id
            WHERE es.id = %s
        """,
            (submission_id,),
        )
        sub = cur.fetchone()
        if not sub:
            raise NotFoundError("Submission not found")
        if sub["status"] != "in_progress":
            raise AlreadySubmittedError()

        exam_id = sub["exam_id"]
        cur.execute(
            """
            SELECT id, position, question_snapshot, max_marks
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY position ASC
        """,
            (exam_id,),
        )
        eq_rows = cur.fetchall()

        eq_map_by_id = {stringify_id(eq["id"]): eq for eq in eq_rows}
        eq_map_by_q_id = {}
        for eq in eq_rows:
            snapshot = maybe_json_load(eq["question_snapshot"], None)
            q_id = snapshot.get("question_id")
            if q_id:
                eq_map_by_q_id[q_id] = eq

        score = 0
        graded_answers = []

        for ans in answers:
            eq_id = ans.get("exam_question_id")
            q_id = ans.get("question_id")

            eq = None
            if eq_id:
                eq = eq_map_by_id.get(eq_id)
            elif q_id:
                eq = eq_map_by_q_id.get(q_id)

            if not eq:
                graded_answers.append(ans)
                continue

            snapshot = maybe_json_load(eq["question_snapshot"], None)

            is_correct = False
            marks_earned = 0

            if snapshot.get("question_type") == "multiple_choice":
                correct_idx = snapshot.get("correct_answer_index")
                user_idx = ans.get("answer_index")
                if user_idx is None and ans.get("selected_options"):
                    selected = ans.get("selected_options")
                    if isinstance(selected, list) and len(selected) > 0:
                        user_idx = selected[0]

                is_correct = correct_idx is not None and user_idx == correct_idx
                marks_earned = eq["max_marks"] if is_correct else 0

            graded_answer = {
                **ans,
                "exam_question_id": stringify_id(eq["id"]),
                "is_correct": is_correct,
                "marks_earned": marks_earned,
            }
            graded_answers.append(graded_answer)
            score += marks_earned

            selected_options = ans.get("selected_options")
            if selected_options is None and ans.get("answer_index") is not None:
                selected_options = [ans.get("answer_index")]

            cur.execute(
                """
                INSERT INTO exam_answers (
                    submission_id, exam_question_id, question_snapshot,
                    answer_text, selected_options, time_spent_seconds,
                    is_correct, marks_earned
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    submission_id,
                    eq["id"],
                    json_lib.dumps(snapshot),
                    ans.get("answer_text"),
                    json_lib.dumps(selected_options) if selected_options else None,
                    ans.get("time_spent_seconds"),
                    is_correct,
                    marks_earned,
                ),
            )

        cur.execute(
            """
            UPDATE exam_submissions
            SET score = %s,
                total_marks = %s,
                time_spent_seconds = %s,
                status = 'submitted',
                submitted_at = now()
            WHERE id = %s
            RETURNING id, submitted_at, score, total_marks
        """,
            (
                score,
                sub["total_marks"],
                time_spent_seconds,
                submission_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        return {
            "submission_id": stringify_id(row["id"]),
            "submitted_at": maybe_iso(row["submitted_at"]),
            "score": row["score"],
            "total_marks": row["total_marks"],
            "status": "submitted",
        }


def get_exam_submissions(exam_id: str) -> List[Dict[str, Any]]:
    sql = """
    SELECT es.id, es.student_id, es.attempt_no, es.score, es.total_marks,
           es.time_spent_seconds, es.status, es.started_at, es.submitted_at,
           es.teacher_comment, es.graded_by, es.graded_at, es.meta,
           u.full_name AS student_name, u.email AS student_email
    FROM exam_submissions es
    JOIN users u ON u.id = es.student_id
    WHERE es.exam_id = %s
    ORDER BY es.submitted_at DESC NULLS LAST, es.started_at DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id,))
        rows = cur.fetchall() or []
        submission_ids = [r["id"] for r in rows]
        answers_map = _fetch_exam_answers_map(
            cur, submission_ids, include_attachments=True
        )
        return [
            map_exam_submission_row(
                row,
                answers=answers_map.get(stringify_id(row["id"]), []),
                include_student=True,
                include_graded_by=True,
            )
            for row in rows
        ]


def get_student_exam_submissions(exam_id: str, student_id: str) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, attempt_no, score, total_marks, time_spent_seconds, status,
           started_at, submitted_at, teacher_comment, graded_at, meta
    FROM exam_submissions
    WHERE exam_id = %s AND student_id = %s
    ORDER BY attempt_no DESC
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (exam_id, student_id))
        rows = cur.fetchall() or []
        submission_ids = [r["id"] for r in rows]
        answers_map = _fetch_exam_answers_map(cur, submission_ids)
        return [
            map_exam_submission_row(
                row,
                answers=answers_map.get(stringify_id(row["id"]), []),
            )
            for row in rows
        ]


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


def get_submission_with_answers(submission_id: str) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, exam_id, student_id, score, total_marks, status,
                   started_at, submitted_at, teacher_comment, graded_at, graded_by,
                   grading_source, meta
            FROM exam_submissions
            WHERE id = %s
        """,
            (submission_id,),
        )
        sub = cur.fetchone()

        if not sub:
            return None

        answers_map = _fetch_exam_answers_map(cur, [submission_id])
        return map_exam_submission_row(
            sub,
            answers=answers_map.get(submission_id, []),
            include_grading_source=True,
        )


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
    "_default_exam_title",
    "ai_grade_exam_submission",
    "delete_exam",
    "get_exam_by_id",
    "get_exam_submissions",
    "get_exams_by_class",
    "get_student_exam_submissions",
    "get_submission_with_answers",
    "grade_exam_submission",
    "publish_exam",
    "save_exam",
    "start_exam_submission",
    "submit_exam",
    "update_exam",
]
