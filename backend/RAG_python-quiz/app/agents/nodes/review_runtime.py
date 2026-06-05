from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from app.agents.nodes.text_utils import strip_code_fences


def parse_review_json(raw_text: str, *, logger) -> Dict[str, Any]:
    if not raw_text or not raw_text.strip():
        raise RuntimeError("API returned empty content during review")

    cleaned_text = strip_code_fences(raw_text)
    try:
        result = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        start_idx = cleaned_text.find("{")
        end_idx = cleaned_text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                result = json.loads(cleaned_text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                logger.error("[Reviewer] JSON parse failed - raw preview: %s", raw_text[:300])
                raise RuntimeError(f"API returned unparseable review JSON: {exc}") from exc
        else:
            logger.error("[Reviewer] JSON parse failed - raw preview: %s", raw_text[:300])
            raise RuntimeError(f"API returned unparseable review JSON: {exc}") from exc

    if not isinstance(result, dict):
        raise RuntimeError("API returned review payload that is not a JSON object")
    return result


def build_review_content(
    prompt: str,
    image_paths: Optional[List[str]],
    *,
    get_absolute_image_path: Callable[[str], str],
    load_image_as_base64: Callable[[str], tuple[str, str]],
    logger,
) -> List[Dict[str, Any]]:
    content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

    if not image_paths:
        return content_list

    for image_path in image_paths:
        abs_path = get_absolute_image_path(image_path)
        if not os.path.exists(abs_path):
            logger.warning("[Reviewer] Image not found: %s", abs_path)
            continue
        try:
            mime_type, b64_data = load_image_as_base64(abs_path)
            content_list.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                }
            )
        except Exception as exc:
            logger.warning("[Reviewer] Failed to load image %s: %s", abs_path, exc)

    return content_list


async def run_review_request(
    api_key: str,
    prompt: str,
    model_name: str,
    image_paths: Optional[List[str]],
    *,
    schema: Dict[str, Any],
    get_llm_client: Callable[[str], Any],
    extract_text: Callable[[Any, str], str],
    to_thread: Callable[..., Any],
    get_absolute_image_path: Callable[[str], str],
    load_image_as_base64: Callable[[str], tuple[str, str]],
    logger,
) -> Dict[str, Any]:
    client = get_llm_client(api_key)
    content_list = build_review_content(
        prompt,
        image_paths,
        get_absolute_image_path=get_absolute_image_path,
        load_image_as_base64=load_image_as_base64,
        logger=logger,
    )

    response = await to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": content_list}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "review_response",
                "strict": False,
                "schema": schema,
            },
        },
    )

    return parse_review_json(extract_text(response, "exam review"), logger=logger)
