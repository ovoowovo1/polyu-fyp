# -*- coding: utf-8 -*-
import psycopg2
from datetime import datetime

from app.config import get_settings
from app.services.pg_classes_service import (
    _get_user_by_email,
    _is_class_owned_by_teacher,
    _is_student_exists,
    create_class_for_teacher,
    invite_student_to_class,
    is_user_teacher,
    list_classes_by_teacher,
    list_classes_for_student,
)
from app.services.pg_db import _get_conn
from app.services.pg_exam_crud import (
    _default_exam_title,
    delete_exam,
    get_exam_by_id,
    get_exams_by_class,
    publish_exam,
    save_exam,
    update_exam,
)
from app.services.pg_exam_grading_service import (
    ai_grade_exam_submission,
    grade_exam_submission,
)
from app.services.pg_exam_submission_service import (
    get_exam_submissions,
    get_student_exam_submissions,
    get_submission_with_answers,
    start_exam_submission,
    submit_exam,
)
from app.services.pg_files_service import (
    delete_file,
    get_files_list,
    get_files_text_content,
    get_source_details_by_chunk_id,
    get_specific_file,
    rename_file,
)
from app.services.pg_quiz_service import (
    _default_quiz_name,
    delete_quiz,
    get_all_quizzes,
    get_quiz_by_id,
    get_quiz_submissions,
    get_quizzes_by_class,
    get_student_quiz_submission,
    save_quiz,
    submit_quiz_result,
    update_quiz,
    QuizService,
    get_quiz_service,
)
from app.services.pg_retrieval_service import (
    create_graph_from_document,
    find_document_by_hash,
    get_chunks_missing_embeddings,
    retrieve_context_by_keywords,
    retrieve_graph_context,
    update_chunk_embeddings,
)
from app.services.pg_shared import (
    VALID_EMBEDDING_COLUMNS,
    _get_embedding_column,
    _to_pgvector,
)


def setup_vector_index() -> None:
    """Compatibility no-op kept for the existing startup hook."""
    return None


__all__ = [
    "VALID_EMBEDDING_COLUMNS",
    "_default_exam_title",
    "_default_quiz_name",
    "_get_conn",
    "_get_embedding_column",
    "_get_user_by_email",
    "_is_class_owned_by_teacher",
    "_is_student_exists",
    "_to_pgvector",
    "ai_grade_exam_submission",
    "create_class_for_teacher",
    "create_graph_from_document",
    "datetime",
    "delete_exam",
    "delete_file",
    "delete_quiz",
    "find_document_by_hash",
    "get_all_quizzes",
    "get_chunks_missing_embeddings",
    "get_exam_by_id",
    "get_exam_submissions",
    "get_exams_by_class",
    "get_files_list",
    "get_files_text_content",
    "get_quiz_by_id",
    "get_quiz_submissions",
    "get_quizzes_by_class",
    "get_settings",
    "get_source_details_by_chunk_id",
    "get_specific_file",
    "get_student_exam_submissions",
    "get_student_quiz_submission",
    "get_submission_with_answers",
    "grade_exam_submission",
    "invite_student_to_class",
    "is_user_teacher",
    "list_classes_by_teacher",
    "list_classes_for_student",
    "psycopg2",
    "publish_exam",
    "rename_file",
    "retrieve_context_by_keywords",
    "retrieve_graph_context",
    "save_exam",
    "save_quiz",
    "setup_vector_index",
    "start_exam_submission",
    "submit_exam",
    "submit_quiz_result",
    "update_chunk_embeddings",
    "update_exam",
    "update_quiz",
    "QuizService",
    "get_quiz_service",
]
