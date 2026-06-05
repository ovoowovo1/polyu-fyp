# -*- coding: utf-8 -*-
"""Matplotlib generation helpers for visualizer."""

import asyncio
import os
from typing import Callable


def strip_code_fence(code: str) -> str:
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    return code.strip()


def execute_matplotlib_code(code: str, *, logger) -> bool:
    try:
        compile(code, "<string>", "exec")
        exec_globals = {
            "__builtins__": __builtins__,
        }
        exec(code, exec_globals)
        return True
    except SyntaxError as exc:
        logger.error("[Visualizer] Matplotlib code has invalid syntax: %s", exc)
        logger.debug("[Visualizer] Generated Matplotlib code:\n%s", code)
        return False
    except Exception as exc:
        logger.error("[Visualizer] Matplotlib code execution failed: %s", exc)
        logger.debug("[Visualizer] Generated Matplotlib code:\n%s", code)
        return False


async def generate_chart_code(
    *,
    api_key: str,
    description: str,
    output_path: str,
    model_name: str,
    get_client: Callable,
    extract_text: Callable,
    build_prompt: Callable,
) -> str:
    client = get_client(api_key)
    prompt = build_prompt(description, output_path)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return strip_code_fence(extract_text(response, "Visualizer Matplotlib code generation"))


async def generate_chart_with_matplotlib(
    *,
    api_key: str,
    description: str,
    output_path: str,
    model_name: str,
    generate_code: Callable,
    execute_code: Callable,
    logger,
) -> bool:
    code = await generate_code(api_key, description, output_path, model_name)
    logger.debug("[Visualizer] Generated Matplotlib code preview:\n%s...", code[:500])
    success = await asyncio.to_thread(execute_code, code)
    return success and os.path.exists(output_path)
