from __future__ import annotations

from typing import Any


_SUMMARY_LIMIT = 240


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _truncate_text(value: Any, limit: int = _SUMMARY_LIMIT) -> str:
    if value is None:
        return "None"

    text = str(value).replace("\n", "\\n")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _safe_repr(value: Any, limit: int = _SUMMARY_LIMIT) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"

    text = text.replace("\n", "\\n")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _build_response_summary(response: Any) -> str:
    if response is None:
        return "response=None"

    choices = _get_attr(response, "choices")
    summary_parts = [f"response_type={type(response).__name__}"]

    model_name = _get_attr(response, "model")
    if model_name:
        summary_parts.append(f"model={_truncate_text(model_name)}")

    if choices is None:
        summary_parts.append("choices=None")
        return ", ".join(summary_parts)

    if isinstance(choices, list):
        summary_parts.append(f"choices_len={len(choices)}")
        first_choice = choices[0] if choices else None
    else:
        summary_parts.append(f"choices_type={type(choices).__name__}")
        first_choice = None

    finish_reason = _get_attr(first_choice, "finish_reason")
    if finish_reason:
        summary_parts.append(f"finish_reason={_truncate_text(finish_reason)}")

    message = _get_attr(first_choice, "message")
    if message is None:
        summary_parts.append("message=None")
    else:
        content = _get_attr(message, "content")
        refusal = _get_attr(message, "refusal")
        summary_parts.append(f"content_type={type(content).__name__}")
        if isinstance(content, str):
            summary_parts.append(f"content_preview={_safe_repr(content)}")
        elif isinstance(content, list):
            summary_parts.append(f"content_parts={len(content)}")
        elif content is not None:
            summary_parts.append(f"content_preview={_safe_repr(content)}")
        if refusal:
            summary_parts.append(f"refusal={_safe_repr(refusal)}")

    return ", ".join(summary_parts)


def _extract_text_from_parts(parts: list[Any]) -> str:
    text_parts: list[str] = []

    for part in parts:
        part_type = _get_attr(part, "type")
        part_text = _get_attr(part, "text")

        if part_type == "text" and isinstance(part_text, str):
            text_parts.append(part_text)
            continue

        if part_type is None and isinstance(part_text, str):
            text_parts.append(part_text)

    return "".join(text_parts)


def _raise_malformed(
    operation_name: str,
    detail: str,
    response: Any,
    *,
    finish_reason: Any = None,
    refusal: Any = None,
) -> None:
    error_parts = [f"{operation_name} returned malformed chat completion: {detail}"]

    if finish_reason:
        error_parts.append(f"finish_reason={_truncate_text(finish_reason)}")

    if refusal:
        error_parts.append(f"refusal={_safe_repr(refusal)}")

    error_parts.append(f"summary=({_build_response_summary(response)})")
    raise RuntimeError("; ".join(error_parts))


def extract_chat_completion_text(response: Any, operation_name: str) -> str:
    if response is None:
        _raise_malformed(operation_name, "response is None", response)

    choices = _get_attr(response, "choices")
    if choices is None:
        _raise_malformed(operation_name, "choices is None", response)

    if not isinstance(choices, list):
        _raise_malformed(
            operation_name,
            f"choices has unexpected type {type(choices).__name__}",
            response,
        )

    if not choices:
        _raise_malformed(operation_name, "choices is empty", response)

    first_choice = choices[0]
    finish_reason = _get_attr(first_choice, "finish_reason")
    message = _get_attr(first_choice, "message")
    if message is None:
        _raise_malformed(
            operation_name,
            "first choice has no message",
            response,
            finish_reason=finish_reason,
        )

    content = _get_attr(message, "content")
    refusal = _get_attr(message, "refusal")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text = _extract_text_from_parts(content)
        if text:
            return text

        _raise_malformed(
            operation_name,
            "message.content list contained no text parts",
            response,
            finish_reason=finish_reason,
            refusal=refusal,
        )

    if content is None:
        detail = "message.content is None"
    else:
        detail = f"message.content has unexpected type {type(content).__name__}"

    _raise_malformed(
        operation_name,
        detail,
        response,
        finish_reason=finish_reason,
        refusal=refusal,
    )
