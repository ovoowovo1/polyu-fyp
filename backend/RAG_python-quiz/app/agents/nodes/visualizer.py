# -*- coding: utf-8 -*-
"""Visualizer node for generating chart and illustration assets for exam questions."""

import asyncio
import base64
import json
import os
import uuid
from typing import Any, Dict, List, Literal, Optional

from app.agents.schemas import ExamQuestion
from app.config import get_settings
from app.logger import get_logger
from app.utils.api_key_manager import get_default_llm_model_name, get_llm_client, with_llm_retry_async
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)

# Model configuration
CLASSIFICATION_MODEL = "google/gemini-2.5-flash-lite"
IMAGE_GENERATION_MODEL = "google/gemini-3.1-flash-image-preview"

# Generated image directory
IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "static",
    "images",
)
os.makedirs(IMAGES_DIR, exist_ok=True)


# ============================================================================
# Image type classification
# ============================================================================

async def _classify_image_type(api_key: str, description: str) -> Literal["chart", "illustration"]:
    """Classify an image description as a chart or a non-chart illustration."""
    client = get_llm_client(api_key)

    prompt = f"""Please analyze the following image description and determine if it is a "Statistical Chart" or a "Non-Chart Illustration".

## Image Description
{description}

## Classification Criteria
- **chart** (Statistical Chart): Bar chart, line chart, pie chart, scatter plot, histogram, area chart, radar chart, etc., that can be visualized using Matplotlib.
- **illustration** (Non-Chart Illustration): Diagram, concept map, flowchart, architecture diagram, scene illustration, object icon, etc., that requires drawing specific graphics.
"""

    classification_schema = {
        "type": "object",
        "properties": {
            "image_type": {
                "type": "string",
                "enum": ["chart", "illustration"],
                "description": "Image Type: chart (Statistical Chart) or illustration (Non-Chart Illustration)",
            }
        },
        "required": ["image_type"],
        "additionalProperties": False,
    }

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=CLASSIFICATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "image_classification",
                "strict": True,
                "schema": classification_schema,
            },
        },
    )

    result_text = extract_chat_completion_text(response, "Visualizer image type classification")

    try:
        result = json.loads(result_text)
        image_type = result.get("image_type", "illustration")
        if image_type in ["chart", "illustration"]:
            return image_type
    except json.JSONDecodeError:
        logger.warning("[Visualizer] Failed to parse image classification JSON: %s", result_text)

    return "illustration"


# ============================================================================
# Matplotlib chart generation
# ============================================================================

def _build_code_generation_prompt(image_description: str, output_path: str) -> str:
    """Build the prompt used to request executable Matplotlib code."""
    safe_path = output_path.replace("\\", "/")

    return f"""You are a Python data visualization expert. Please generate executable Matplotlib Python code based on the following chart description.

## Chart Description
{image_description}

## Strict Requirements
1. Output only pure Python code, no explanations, comments, or markdown tags.
2. Code must be syntactically correct and directly executable.
3. Use simple and direct code style, avoid complex structures.
4. Use single quotes for all strings.
5. Do not use f-strings or multi-line strings.
6. Do not use plt.show().
7. Chart save path must be: {safe_path}

## Mandatory Code Structure
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(10, 6))

# Add plotting code here
# Use ax.bar(), ax.plot(), ax.pie() etc.

ax.set_title('Title')
ax.set_xlabel('X Axis')
ax.set_ylabel('Y Axis')

plt.tight_layout()
plt.savefig('{safe_path}', dpi=150, bbox_inches='tight')
plt.close()

Now please generate the complete code based on the chart description:"""


def _execute_matplotlib_code(code: str) -> bool:
    """Execute generated Matplotlib code in a minimal globals scope."""
    try:
        compile(code, "<string>", "exec")
        exec_globals = {
            "__builtins__": __builtins__,
        }
        exec(code, exec_globals)
        return True
    except SyntaxError as e:
        logger.error("[Visualizer] Matplotlib code has invalid syntax: %s", e)
        logger.debug("[Visualizer] Generated Matplotlib code:\n%s", code)
        return False
    except Exception as e:
        logger.error("[Visualizer] Matplotlib code execution failed: %s", e)
        logger.debug("[Visualizer] Generated Matplotlib code:\n%s", code)
        return False


async def _generate_chart_code(api_key: str, description: str, output_path: str, model_name: str) -> str:
    """Generate Matplotlib code from the LLM."""
    client = get_llm_client(api_key)
    prompt = _build_code_generation_prompt(description, output_path)

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )

    code = extract_chat_completion_text(response, "Visualizer Matplotlib code generation")

    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]

    return code.strip()


async def _generate_chart_with_matplotlib(
    api_key: str,
    description: str,
    output_path: str,
    model_name: str,
) -> bool:
    """Generate a chart image with Matplotlib and return whether it succeeded."""
    code = await _generate_chart_code(api_key, description, output_path, model_name)

    logger.debug("[Visualizer] Generated Matplotlib code preview:\n%s...", code[:500])
    success = await asyncio.to_thread(_execute_matplotlib_code, code)

    return success and os.path.exists(output_path)


# ============================================================================
# Direct image generation
# ============================================================================

async def _transform_to_image_prompt(api_key: str, description: str) -> str:
    """Convert the description into a better prompt for image generation."""
    client = get_llm_client(api_key)

    prompt = f"""You are a professional AI image generation prompt engineer. Please convert the following image description into a prompt suitable for an AI image generation model.

## Original Description
{description}

## Conversion Requirements
1. Output in English (AI image generation models work better with English).
2. Add appropriate style descriptions (e.g., clean vector illustration, flat design, isometric style, etc.).
3. Description should be specific and clear.
4. Suitable for educational or academic illustrations.
5. Avoid complex text content.

## Output Requirements
Output only the converted prompt, without any explanation or extra text."""

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=CLASSIFICATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )

    result = extract_chat_completion_text(response, "Image prompt transformation").strip()
    return result if result else description


async def _generate_image_with_gemini(api_key: str, description: str, output_path: str) -> bool:
    """Generate an illustration image and write it to disk."""
    client = get_llm_client(api_key)

    optimized_prompt = await _transform_to_image_prompt(api_key, description)
    logger.debug("[Visualizer] Optimized image prompt: %s...", optimized_prompt[:200])

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=IMAGE_GENERATION_MODEL,
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
            image_url = image_item.get("image_url") if isinstance(image_item, dict) else getattr(image_item, "image_url", None)
            url = image_url.get("url") if isinstance(image_url, dict) else getattr(image_url, "url", None)

            if not url or not isinstance(url, str):
                continue

            if not url.startswith("data:image/") or ";base64," not in url:
                logger.warning("[Visualizer] OpenRouter image URL is not a valid base64 data URL")
                continue

            _, encoded = url.split(";base64,", 1)
            try:
                image_bytes = base64.b64decode(encoded)
            except Exception as e:
                logger.warning("[Visualizer] Failed to decode OpenRouter image base64: %s", e)
                continue

            if not image_bytes:
                logger.warning("[Visualizer] Decoded OpenRouter image is empty")
                continue

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            logger.info("[Visualizer] OpenRouter image saved to: %s", output_path)
            return True

        logger.warning("[Visualizer] OpenRouter response did not contain any usable image data")
        return False

    except Exception as e:
        logger.error("[Visualizer] OpenRouter image generation failed: %s", e)
        return False


# ============================================================================
# Question image orchestration
# ============================================================================

async def _generate_single_image(question: ExamQuestion, exam_id: str, model_name: str) -> Optional[str]:
    """Generate one image asset for a question when an image description exists."""
    if not question.image_description:
        return None

    image_filename = f"{exam_id}_{question.question_id}.png"
    output_path = os.path.join(IMAGES_DIR, image_filename)
    relative_path = f"/static/images/{image_filename}"

    logger.info("[Visualizer] Starting image generation for question_id=%s", question.question_id)

    try:
        image_type = await with_llm_retry_async(
            "Image type classification",
            _classify_image_type,
            question.image_description,
            error_type=RuntimeError,
        )

        logger.info("[Visualizer] Image type classified as: %s", image_type)

        success = False

        if image_type == "chart":
            logger.info("[Visualizer] Generating chart with Matplotlib")
            success = await with_llm_retry_async(
                "Matplotlib chart generation",
                _generate_chart_with_matplotlib,
                question.image_description,
                output_path,
                model_name,
                error_type=RuntimeError,
            )
        else:
            logger.info("[Visualizer] Generating illustration with Gemini image API")
            success = await with_llm_retry_async(
                "Gemini image generation",
                _generate_image_with_gemini,
                question.image_description,
                output_path,
                error_type=RuntimeError,
            )

        if success and os.path.exists(output_path):
            logger.info("[Visualizer] Image generated successfully: %s", relative_path)
            return relative_path

        logger.warning("[Visualizer] Image generation did not produce a file: %s", output_path)
        return None

    except Exception as e:
        logger.error("[Visualizer] Unexpected image generation failure: %s", e)
        return None


async def visualizer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate image assets for questions and store image paths back into state."""
    questions: List[ExamQuestion] = state.get("questions", [])
    exam_id = state.get("exam_id", "exam_unknown")
    questions_with_images = [q for q in questions if q.image_description]

    if not questions_with_images:
        logger.info("[Visualizer] No questions require generated images")
        return {
            **state,
            "images": {},
        }

    logger.info("[Visualizer] Generating images for %s questions", len(questions_with_images))

    settings = get_settings()
    model_name = settings.llm_model or "gemini-2.5-flash"

    images: Dict[str, str] = {}
    updated_questions: List[ExamQuestion] = []

    for question in questions:
        if question.image_description:
            image_path = await _generate_single_image(question, exam_id, model_name)

            if image_path:
                question.image_path = image_path
                images[question.question_id] = image_path

        updated_questions.append(question)

    logger.info("[Visualizer] Image generation finished - success=%s/%s", len(images), len(questions_with_images))

    return {
        **state,
        "questions": updated_questions,
        "images": images,
    }
