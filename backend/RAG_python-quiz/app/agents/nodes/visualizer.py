# -*- coding: utf-8 -*-
"""Visualizer node facade for generating chart and illustration assets."""

import asyncio
import json
import os
from typing import Any, Dict, List, Literal, Optional

from app.agents.nodes.visualizer_chart import (
    execute_matplotlib_code,
    generate_chart_code,
    generate_chart_with_matplotlib,
)
from app.agents.nodes.visualizer_image import (
    generate_image_with_gemini,
    transform_to_image_prompt,
)
from app.agents.nodes.visualizer_prompts import (
    build_classification_prompt,
    build_classification_schema,
    build_code_generation_prompt,
    build_image_prompt_transform_prompt,
)
from app.agents.nodes.visualizer_workflow import generate_single_image
from app.agents.schemas import ExamQuestion
from app.config import get_settings
from app.logger import get_logger
from app.utils.api_key_manager import get_llm_client, with_llm_retry_async
from app.utils.openai_response import extract_chat_completion_text

logger = get_logger(__name__)

CLASSIFICATION_MODEL = "google/gemini-2.5-flash-lite"
IMAGE_GENERATION_MODEL = "google/gemini-3.1-flash-image-preview"

IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "static",
    "images",
)
os.makedirs(IMAGES_DIR, exist_ok=True)


async def _classify_image_type(api_key: str, description: str) -> Literal["chart", "illustration"]:
    """Classify an image description as a chart or a non-chart illustration."""
    client = get_llm_client(api_key)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=CLASSIFICATION_MODEL,
        messages=[{"role": "user", "content": build_classification_prompt(description)}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "image_classification",
                "strict": True,
                "schema": build_classification_schema(),
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


def _build_code_generation_prompt(image_description: str, output_path: str) -> str:
    """Build the prompt used to request executable Matplotlib code."""
    return build_code_generation_prompt(image_description, output_path)


def _execute_matplotlib_code(code: str) -> bool:
    """Execute generated Matplotlib code in a minimal globals scope."""
    return execute_matplotlib_code(code, logger=logger)


async def _generate_chart_code(api_key: str, description: str, output_path: str, model_name: str) -> str:
    """Generate Matplotlib code from the LLM."""
    return await generate_chart_code(
        api_key=api_key,
        description=description,
        output_path=output_path,
        model_name=model_name,
        get_client=get_llm_client,
        extract_text=extract_chat_completion_text,
        build_prompt=_build_code_generation_prompt,
    )


async def _generate_chart_with_matplotlib(
    api_key: str,
    description: str,
    output_path: str,
    model_name: str,
) -> bool:
    """Generate a chart image with Matplotlib and return whether it succeeded."""
    return await generate_chart_with_matplotlib(
        api_key=api_key,
        description=description,
        output_path=output_path,
        model_name=model_name,
        generate_code=_generate_chart_code,
        execute_code=_execute_matplotlib_code,
        logger=logger,
    )


async def _transform_to_image_prompt(api_key: str, description: str) -> str:
    """Convert the description into a better prompt for image generation."""
    return await transform_to_image_prompt(
        api_key=api_key,
        description=description,
        model_name=CLASSIFICATION_MODEL,
        get_client=get_llm_client,
        extract_text=extract_chat_completion_text,
        build_prompt=build_image_prompt_transform_prompt,
    )


async def _generate_image_with_gemini(api_key: str, description: str, output_path: str) -> bool:
    """Generate an illustration image and write it to disk."""
    return await generate_image_with_gemini(
        api_key=api_key,
        description=description,
        output_path=output_path,
        model_name=IMAGE_GENERATION_MODEL,
        get_client=get_llm_client,
        transform_prompt=_transform_to_image_prompt,
        logger=logger,
    )


async def _generate_single_image(question: ExamQuestion, exam_id: str, model_name: str) -> Optional[str]:
    """Generate one image asset for a question when an image description exists."""
    return await generate_single_image(
        question=question,
        exam_id=exam_id,
        model_name=model_name,
        images_dir=IMAGES_DIR,
        retry_async=with_llm_retry_async,
        classify_image_type=_classify_image_type,
        generate_chart=_generate_chart_with_matplotlib,
        generate_image=_generate_image_with_gemini,
        logger=logger,
    )


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
