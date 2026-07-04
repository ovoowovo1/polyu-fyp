from __future__ import annotations

from typing import Any, Callable


def classes_user_namespace(user_id: str) -> str:
    return f"classes:user:{user_id}"


def quiz_list_namespace() -> str:
    return "quiz:list"


def quiz_detail_namespace(quiz_id: str) -> str:
    return f"quiz:detail:{quiz_id}"


def exam_list_namespace() -> str:
    return "exam:list"


def exam_detail_namespace(exam_id: str) -> str:
    return f"exam:detail:{exam_id}"


def files_list_namespace() -> str:
    return "files:list"


def file_detail_namespace(file_id: str) -> str:
    return f"files:detail:{file_id}"


def chunk_source_namespace() -> str:
    return "chunks:source-details"


def rag_retrieval_namespace() -> str:
    return "rag:retrieval"


def can_use_cache(checker: Callable[..., Any], *args: Any) -> bool:
    try:
        return bool(checker(*args))
    except Exception:
        return False


def id_from_result(result: Any, *field_names: str) -> str:
    if isinstance(result, dict):
        return str(_first_present(result, field_names) or "")
    for field_name in field_names:
        value = getattr(result, field_name, None)
        if value:
            return str(value)
    return ""


def _first_present(result: dict[str, Any], field_names: tuple[str, ...]) -> Any:
    for field_name in field_names:
        value = result.get(field_name)
        if value:
            return value
    return None
