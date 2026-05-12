from __future__ import annotations

import asyncio
from typing import Optional

from app.utils.api_key_manager import (
    get_default_llm_model_name,
    get_llm_client,
    with_llm_retry_async,
)
from app.utils.openai_response import extract_chat_completion_text


async def generate_text_completion(
    prompt: str,
    *,
    operation_name: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> str:
    async def _generate(api_key: str) -> str:
        client = get_llm_client(api_key)
        model_name = get_default_llm_model_name()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=messages,
            temperature=temperature,
        )
        text = extract_chat_completion_text(response, operation_name)
        if not text:
            raise RuntimeError(f"{operation_name} returned empty content")
        return text.strip()

    return await with_llm_retry_async(
        operation_name,
        _generate,
        error_type=RuntimeError,
    )
