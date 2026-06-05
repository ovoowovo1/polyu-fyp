# -*- coding: utf-8 -*-
"""Question-level visualizer orchestration."""

import os
from typing import Optional

from app.agents.schemas import ExamQuestion


async def generate_single_image(
    *,
    question: ExamQuestion,
    exam_id: str,
    model_name: str,
    images_dir: str,
    retry_async,
    classify_image_type,
    generate_chart,
    generate_image,
    logger,
) -> Optional[str]:
    if not question.image_description:
        return None

    image_filename = f"{exam_id}_{question.question_id}.png"
    output_path = os.path.join(images_dir, image_filename)
    relative_path = f"/static/images/{image_filename}"

    logger.info("[Visualizer] Starting image generation for question_id=%s", question.question_id)

    try:
        image_type = await retry_async(
            "Image type classification",
            classify_image_type,
            question.image_description,
            error_type=RuntimeError,
        )
        logger.info("[Visualizer] Image type classified as: %s", image_type)

        if image_type == "chart":
            logger.info("[Visualizer] Generating chart with Matplotlib")
            success = await retry_async(
                "Matplotlib chart generation",
                generate_chart,
                question.image_description,
                output_path,
                model_name,
                error_type=RuntimeError,
            )
        else:
            logger.info("[Visualizer] Generating illustration with Gemini image API")
            success = await retry_async(
                "Gemini image generation",
                generate_image,
                question.image_description,
                output_path,
                error_type=RuntimeError,
            )

        if success and os.path.exists(output_path):
            logger.info("[Visualizer] Image generated successfully: %s", relative_path)
            return relative_path

        logger.warning("[Visualizer] Image generation did not produce a file: %s", output_path)
        return None
    except Exception as exc:
        logger.error("[Visualizer] Unexpected image generation failure: %s", exc)
        return None
