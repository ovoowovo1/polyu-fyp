# -*- coding: utf-8 -*-
"""
Visualizer Node - ?”??蝭暺?The Coder嚗?雿輻 Python 隞?Ⅳ嚗atplotlib嚗??絞閮?銵?撠??銵券?????嚗蝙??Gemini ???? API
"""

from typing import Dict, Any, List, Optional, Literal
import os
import uuid
import json
import asyncio
import base64

from app.agents.schemas import ExamQuestion
from app.config import get_settings
from app.utils.api_key_manager import (
    with_llm_retry_async,
    get_llm_client,
    get_default_llm_model_name
)
from app.utils.openai_response import extract_chat_completion_text
from app.logger import get_logger

logger = get_logger(__name__)

# 璅∪??蔭
CLASSIFICATION_MODEL = "google/gemini-2.5-flash-lite"  # ??隞餃?雿輻頛?璅∪?
IMAGE_GENERATION_MODEL = "google/gemini-3.1-flash-image-preview"  # ????璅∪?

# ??摮?桅?
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "static", "images")

# 蝣箔??桅?摮
os.makedirs(IMAGES_DIR, exist_ok=True)


# ============================================================================
# ??憿???
# ============================================================================

async def _classify_image_type(
    api_key: str,
    description: str
) -> Literal["chart", "illustration"]:
    """
    雿輻 AI ?????膩?舐絞閮?銵券??舫??”??
    
    Args:
        api_key: Gemini API key
        description: ???膩
    
    Returns:
        "chart" - 蝯梯??”嚗???蝺?????嚗?        "illustration" - ??銵剁?蝷箸???敹萄???蝔?蝑?
    """
    client = get_llm_client(api_key)
    
    prompt = f"""Please analyze the following image description and determine if it is a "Statistical Chart" or a "Non-Chart Illustration".

## Image Description
{description}

## Classification Criteria
- **chart** (Statistical Chart): Bar chart, line chart, pie chart, scatter plot, histogram, area chart, radar chart, etc., that can be visualized using Matplotlib.
- **illustration** (Non-Chart Illustration): Diagram, concept map, flowchart, architecture diagram, scene illustration, object icon, etc., that requires drawing specific graphics.
"""

    # 雿輻 JSON schema ?批?踵??澆?
    classification_schema = {
        "type": "object",
        "properties": {
            "image_type": {
                "type": "string",
                "enum": ["chart", "illustration"],
                "description": "Image Type: chart (Statistical Chart) or illustration (Non-Chart Illustration)"
            }
        },
        "required": ["image_type"],
        "additionalProperties": False
    }

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=CLASSIFICATION_MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "image_classification",
                "strict": True,
                "schema": classification_schema
            }
        }
    )
    
    result_text = extract_chat_completion_text(response, "??憿???")
    
    try:
        result = json.loads(result_text)
        image_type = result.get("image_type", "illustration")
        if image_type in ["chart", "illustration"]:
            return image_type
    except json.JSONDecodeError:
        logger.warning(f"[Visualizer] JSON 閫??憭望?嚗蝙?券?閮剖? {result_text}")
    
    return "illustration"


# ============================================================================
# Matplotlib ?”??
# ============================================================================

def _build_code_generation_prompt(image_description: str, output_path: str) -> str:
    """撱箸? Matplotlib 隞?Ⅳ????prompt"""
    # 撠楝敺葉????頧??箸迤??嚗??蝚虫葡頧儔??
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
    """
    ?瑁? Matplotlib 隞?Ⅳ
    
    瘜冽?嚗銝?陛??撖衣???啣?銝哨?
    ?府雿輻?游??函?瘝拳?瑁??啣???    """
    try:
        # ?楊霅舀炎?亥?瘜?        compile(code, '<string>', 'exec')
        
        # 皞??瑁??啣?
        exec_globals = {
            "__builtins__": __builtins__,
        }
        
        # ?瑁?隞?Ⅳ
        exec(code, exec_globals)
        return True
    except SyntaxError as e:
        logger.error(f"[Visualizer] 隞?Ⅳ隤??航炊: {e}")
        logger.debug(f"[Visualizer] ??隞?Ⅳ:\n{code}")
        return False
    except Exception as e:
        logger.error(f"[Visualizer] 隞?Ⅳ?瑁?憭望?: {e}")
        logger.debug(f"[Visualizer] ??隞?Ⅳ:\n{code}")
        return False


async def _generate_chart_code(api_key: str, description: str, output_path: str, model_name: str) -> str:
    """雿輻 Gemini ?? Matplotlib 隞?Ⅳ"""
    client = get_llm_client(api_key)
    prompt = _build_code_generation_prompt(description, output_path)
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    code = extract_chat_completion_text(response, "Matplotlib ?”蝔???")
    
    # Strip markdown code fences if the model returned them.
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    return code.strip()


async def _generate_chart_with_matplotlib(
    api_key: str,
    description: str,
    output_path: str,
    model_name: str
) -> bool:
    """
    雿輻 Matplotlib ???”
    
    Returns:
        bool: ?臬?????”
    """
    # ?? Matplotlib 隞?Ⅳ
    code = await _generate_chart_code(api_key, description, output_path, model_name)
    
    logger.debug(f"[Visualizer] ????Matplotlib 隞?Ⅳ:\n{code[:500]}...")
    
    # ?瑁?隞?Ⅳ???”
    success = await asyncio.to_thread(_execute_matplotlib_code, code)
    
    return success and os.path.exists(output_path)


# ============================================================================
# Gemini ???? API
# ============================================================================

async def _transform_to_image_prompt(
    api_key: str,
    description: str
) -> str:
    """
    雿輻 AI 撠???餈啗????拙????? API ??prompt
    
    Args:
        api_key: Gemini API key
        description: ?????膩
    
    Returns:
        ?芸?敺????? prompt
    """
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
        model=CLASSIFICATION_MODEL,  # 雿輻頛?璅∪?
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    result = extract_chat_completion_text(response, "Image prompt transformation").strip()
    return result if result else description


async def _generate_image_with_gemini(
    api_key: str,
    description: str,
    output_path: str
) -> bool:
    """
    雿輻 OpenRouter ???? API ????
    
    Args:
        api_key: API key
        description: ???膩嚗??????芸???prompt嚗?        output_path: 頛詨頝臬?
    
    Returns:
        bool: ?臬??????
    """
    client = get_llm_client(api_key)
    
    # ???膩頧???? prompt
    optimized_prompt = await _transform_to_image_prompt(api_key, description)
    logger.debug(f"[Visualizer] ?芸?敺??? prompt: {optimized_prompt[:200]}...")
    
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=IMAGE_GENERATION_MODEL,
            messages=[
                {"role": "user", "content": optimized_prompt}
            ],
            modalities=["image", "text"]
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
                logger.warning(f"[Visualizer] Failed to decode OpenRouter image base64: {e}")
                continue

            if not image_bytes:
                logger.warning("[Visualizer] Decoded OpenRouter image is empty")
                continue

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            logger.info(f"[Visualizer] OpenRouter ??????: {output_path}")
            return True

        logger.warning("[Visualizer] OpenRouter response did not contain any usable image data")
        return False
        
    except Exception as e:
        logger.error(f"[Visualizer] OpenRouter ????憭望?: {e}")
        return False


# ============================================================================
# 銝餉??????摩
# ============================================================================

async def _generate_single_image(
    question: ExamQuestion,
    exam_id: str,
    model_name: str
) -> Optional[str]:
    """
    ?箏???桃?????    
    瘚?嚗?    1. AI ?? image_description嚗?銵?vs ??銵剁?
    2. ?寞???蝯??豢????孵?嚗?       - chart: 雿輻 Matplotlib ??蝯梯??”
       - illustration: 雿輻 Gemini ???? API
    """
    if not question.image_description:
        return None
    
    # Build a stable filename for the generated image asset.
    image_filename = f"{exam_id}_{question.question_id}.png"
    output_path = os.path.join(IMAGES_DIR, image_filename)
    relative_path = f"/static/images/{image_filename}"
    
    logger.info(f"[Visualizer] ??????: {question.question_id}")
    
    try:
        # Step 1: AI ????憿?
        image_type = await with_llm_retry_async(
            "??憿???",
            _classify_image_type,
            question.image_description,
            error_type=RuntimeError
        )
        
        logger.info(f"[Visualizer] ??憿???蝯?: {image_type}")
        
        success = False
        
        # Step 2: ?寞???蝯??豢????孵?
        if image_type == "chart":
            # 雿輻 Matplotlib ??蝯梯??”
            logger.info(f"[Visualizer] 雿輻 Matplotlib ???”")
            success = await with_llm_retry_async(
                "Matplotlib ?”??",
                _generate_chart_with_matplotlib,
                question.image_description,
                output_path,
                model_name,
                error_type=RuntimeError
            )
        else:
            # 雿輻 Gemini ???? API ????
            logger.info(f"[Visualizer] 雿輻 Gemini ?? API ????")
            success = await with_llm_retry_async(
                "Gemini ????",
                _generate_image_with_gemini,
                question.image_description,
                output_path,
                error_type=RuntimeError
            )
        
        if success and os.path.exists(output_path):
            logger.info(f"[Visualizer] ??????: {relative_path}")
            return relative_path
        else:
            logger.warning(f"[Visualizer] ????憭望???隞嗡?摮: {output_path}")
            return None
            
    except Exception as e:
        logger.error(f"[Visualizer] ??????隤? {e}")
        return None


async def visualizer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Visualizer Node - ??憿??????    
    ?舀?拍車???孵?嚗?    - 蝯梯??”嚗蝙??Matplotlib ??嚗???蝺?????嚗?    - ??銵冽???雿輻 Gemini ???? API嚗內????敹萄?蝑?
    
    頛詨 State:
        - questions: 憿?”嚗??賣? image_description嚗?        - exam_id: ?岫 ID
    
    頛詨 State ?湔:
        - questions: ?湔敺?憿?”嚗???image_path嚗?        - images: ??頝臬???
    """
    questions: List[ExamQuestion] = state.get("questions", [])
    exam_id = state.get("exam_id", "exam_unknown")
    
    # ?曉?閬?????憿
    questions_with_images = [q for q in questions if q.image_description]
    
    if not questions_with_images:
        logger.info("[Visualizer] No questions require generated images")
        return {
            **state,
            "images": {}
        }
    
    logger.info("[Visualizer] Generating images for %s questions", len(questions_with_images))
    
    settings = get_settings()
    model_name = settings.llm_model or "gemini-2.5-flash"
    
    # 靘?????
    images: Dict[str, str] = {}
    updated_questions: List[ExamQuestion] = []
    
    for question in questions:
        if question.image_description:
            # ????
            image_path = await _generate_single_image(question, exam_id, model_name)
            
            if image_path:
                # ?湔憿??image_path
                question.image_path = image_path
                images[question.question_id] = image_path
        
        updated_questions.append(question)
    
    logger.info(f"[Visualizer] ????摰? - ??: {len(images)}/{len(questions_with_images)}")
    
    return {
        **state,
        "questions": updated_questions,
        "images": images
    }

