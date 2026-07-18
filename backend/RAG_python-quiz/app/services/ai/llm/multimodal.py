from __future__ import annotations

from typing import Any, Iterable


MAX_RAG_IMAGES = 6


def build_multimodal_content(text: str, image_inputs: Iterable[dict[str, Any]] = ()) -> str | list[dict[str, Any]]:
    """Build an OpenAI-compatible text-plus-image message when images exist."""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    seen: set[str] = set()
    for image in image_inputs:
        data_url = image.get("image_data") or image.get("data_url")
        if not data_url or data_url in seen:
            continue
        seen.add(data_url)
        content.append({"type": "image_url", "image_url": {"url": data_url}})
        if len(seen) >= MAX_RAG_IMAGES:
            break
    return content if len(content) > 1 else text
