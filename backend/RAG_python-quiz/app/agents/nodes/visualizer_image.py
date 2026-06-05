# -*- coding: utf-8 -*-
"""Direct illustration generation helpers for visualizer."""

import asyncio
import base64
import os
from typing import Callable, Optional


def extract_image_url(image_item) -> Optional[str]:
    image_url = image_item.get("image_url") if isinstance(image_item, dict) else getattr(image_item, "image_url", None)
    return image_url.get("url") if isinstance(image_url, dict) else getattr(image_url, "url", None)


def decode_data_image_url(url: str, *, logger) -> Optional[bytes]:
    if not url or not isinstance(url, str):
        return None
    if not url.startswith("data:image/") or ";base64," not in url:
        logger.warning("[Visualizer] OpenRouter image URL is not a valid base64 data URL")
        return None
    _, encoded = url.split(";base64,", 1)
    try:
        image_bytes = base64.b64decode(encoded)
    except Exception as exc:
        logger.warning("[Visualizer] Failed to decode OpenRouter image base64: %s", exc)
        return None
    if not image_bytes:
        logger.warning("[Visualizer] Decoded OpenRouter image is empty")
        return None
    return image_bytes


def write_image_bytes(output_path: str, image_bytes: bytes) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as file:
        file.write(image_bytes)


async def transform_to_image_prompt(
    *,
    api_key: str,
    description: str,
    model_name: str,
    get_client: Callable,
    extract_text: Callable,
    build_prompt: Callable,
) -> str:
    client = get_client(api_key)
    prompt = build_prompt(description)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    result = extract_text(response, "Image prompt transformation").strip()
    return result if result else description


async def generate_image_with_gemini(
    *,
    api_key: str,
    description: str,
    output_path: str,
    model_name: str,
    get_client: Callable,
    transform_prompt: Callable,
    logger,
) -> bool:
    client = get_client(api_key)
    optimized_prompt = await transform_prompt(api_key, description)
    logger.debug("[Visualizer] Optimized image prompt: %s...", optimized_prompt[:200])

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[{"role": "user", "content": optimized_prompt}],
            modalities=["image", "text"],
        )

        if not response or not getattr(response, "choices", None):
            logger.warning("[Visualizer] OpenRouter image response has no choices")
            return False

        message = getattr(response.choices[0], "message", None)
        images = getattr(message, "images", None) if message else None
        if not images:
            content = getattr(message, "content", None) if message else None
            logger.warning(
                "[Visualizer] OpenRouter image response contains no images. content=%s",
                str(content)[:200] if content is not None else None,
            )
            return False

        for image_item in images:
            image_bytes = decode_data_image_url(extract_image_url(image_item), logger=logger)
            if not image_bytes:
                continue
            write_image_bytes(output_path, image_bytes)
            logger.info("[Visualizer] OpenRouter image saved to: %s", output_path)
            return True

        logger.warning("[Visualizer] OpenRouter response did not contain any usable image data")
        return False
    except Exception as exc:
        logger.error("[Visualizer] OpenRouter image generation failed: %s", exc)
        return False
