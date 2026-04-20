# -*- coding: utf-8 -*-
"""
Visualizer Node - 圖表生成節點（The Coder）
使用 Python 代碼（Matplotlib）生成統計圖表
對於非圖表類型的圖像，使用 Gemini 圖像生成 API
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
    with_gemini_retry_async,
    get_genai_client,
    get_default_model_name
)
from app.utils.openai_response import extract_chat_completion_text
from app.logger import get_logger

logger = get_logger(__name__)

# 模型配置
CLASSIFICATION_MODEL = "google/gemini-2.5-flash-lite"  # 分類任務使用輕量模型
IMAGE_GENERATION_MODEL = "google/gemini-3.1-flash-image-preview"  # 圖像生成模型

# 圖片存儲目錄
IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "static", "images")

# 確保目錄存在
os.makedirs(IMAGES_DIR, exist_ok=True)


# ============================================================================
# 圖像類型分類
# ============================================================================

async def _classify_image_type(
    api_key: str,
    description: str
) -> Literal["chart", "illustration"]:
    """
    使用 AI 分類圖像描述是統計圖表還是非圖表插圖
    
    Args:
        api_key: Gemini API key
        description: 圖像描述
    
    Returns:
        "chart" - 統計圖表（柱狀圖、折線圖、餅圖等）
        "illustration" - 非圖表（示意圖、概念圖、流程圖等）
    """
    client = get_genai_client(api_key)
    
    prompt = f"""Please analyze the following image description and determine if it is a "Statistical Chart" or a "Non-Chart Illustration".

## Image Description
{description}

## Classification Criteria
- **chart** (Statistical Chart): Bar chart, line chart, pie chart, scatter plot, histogram, area chart, radar chart, etc., that can be visualized using Matplotlib.
- **illustration** (Non-Chart Illustration): Diagram, concept map, flowchart, architecture diagram, scene illustration, object icon, etc., that requires drawing specific graphics.
"""

    # 使用 JSON schema 控制響應格式
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
    
    result_text = extract_chat_completion_text(response, "圖片類型分類")
    
    try:
        result = json.loads(result_text)
        image_type = result.get("image_type", "illustration")
        if image_type in ["chart", "illustration"]:
            return image_type
    except json.JSONDecodeError:
        logger.warning(f"[Visualizer] JSON 解析失敗，使用預設值: {result_text}")
    
    return "illustration"


# ============================================================================
# Matplotlib 圖表生成
# ============================================================================

def _build_code_generation_prompt(image_description: str, output_path: str) -> str:
    """建構 Matplotlib 代碼生成的 prompt"""
    # 將路徑中的反斜線轉換為正斜線，避免字符串轉義問題
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
    執行 Matplotlib 代碼
    
    注意：這是一個簡化的實現。在生產環境中，
    應該使用更安全的沙箱執行環境。
    """
    try:
        # 先編譯檢查語法
        compile(code, '<string>', 'exec')
        
        # 準備執行環境
        exec_globals = {
            "__builtins__": __builtins__,
        }
        
        # 執行代碼
        exec(code, exec_globals)
        return True
    except SyntaxError as e:
        logger.error(f"[Visualizer] 代碼語法錯誤: {e}")
        logger.debug(f"[Visualizer] 問題代碼:\n{code}")
        return False
    except Exception as e:
        logger.error(f"[Visualizer] 代碼執行失敗: {e}")
        logger.debug(f"[Visualizer] 問題代碼:\n{code}")
        return False


async def _generate_chart_code(api_key: str, description: str, output_path: str, model_name: str) -> str:
    """使用 Gemini 生成 Matplotlib 代碼"""
    client = get_genai_client(api_key)
    prompt = _build_code_generation_prompt(description, output_path)
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model_name,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    code = extract_chat_completion_text(response, "Matplotlib 圖表程式生成")
    
    # 清理代碼（移除 markdown 標記）
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
    使用 Matplotlib 生成圖表
    
    Returns:
        bool: 是否成功生成圖表
    """
    # 生成 Matplotlib 代碼
    code = await _generate_chart_code(api_key, description, output_path, model_name)
    
    logger.debug(f"[Visualizer] 生成的 Matplotlib 代碼:\n{code[:500]}...")
    
    # 執行代碼生成圖表
    success = await asyncio.to_thread(_execute_matplotlib_code, code)
    
    return success and os.path.exists(output_path)


# ============================================================================
# Gemini 圖像生成 API
# ============================================================================

async def _transform_to_image_prompt(
    api_key: str,
    description: str
) -> str:
    """
    使用 AI 將圖像描述轉換成適合圖像生成 API 的 prompt
    
    Args:
        api_key: Gemini API key
        description: 原始圖像描述
    
    Returns:
        優化後的圖像生成 prompt
    """
    client = get_genai_client(api_key)
    
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
        model=CLASSIFICATION_MODEL,  # 使用輕量模型
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    result = extract_chat_completion_text(response, "圖片提示詞轉換").strip()
    return result if result else description


async def _generate_image_with_gemini(
    api_key: str,
    description: str,
    output_path: str
) -> bool:
    """
    使用 OpenRouter 圖像生成 API 生成圖像
    
    Args:
        api_key: API key
        description: 圖像描述（會先轉換成優化的 prompt）
        output_path: 輸出路徑
    
    Returns:
        bool: 是否成功生成圖像
    """
    client = get_genai_client(api_key)
    
    # 先將描述轉換成優化的 prompt
    optimized_prompt = await _transform_to_image_prompt(api_key, description)
    logger.debug(f"[Visualizer] 優化後的圖像 prompt: {optimized_prompt[:200]}...")
    
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
            logger.info(f"[Visualizer] OpenRouter 圖像生成成功: {output_path}")
            return True

        logger.warning("[Visualizer] OpenRouter response did not contain any usable image data")
        return False
        
    except Exception as e:
        logger.error(f"[Visualizer] OpenRouter 圖像生成失敗: {e}")
        return False


# ============================================================================
# 主要圖像生成邏輯
# ============================================================================

async def _generate_single_image(
    question: ExamQuestion,
    exam_id: str,
    model_name: str
) -> Optional[str]:
    """
    為單個題目生成圖像
    
    流程：
    1. AI 分類 image_description（圖表 vs 非圖表）
    2. 根據分類結果選擇生成方式：
       - chart: 使用 Matplotlib 生成統計圖表
       - illustration: 使用 Gemini 圖像生成 API
    """
    if not question.image_description:
        return None
    
    # 生成圖片文件名
    image_filename = f"{exam_id}_{question.question_id}.png"
    output_path = os.path.join(IMAGES_DIR, image_filename)
    relative_path = f"/static/images/{image_filename}"
    
    logger.info(f"[Visualizer] 開始生成圖像: {question.question_id}")
    
    try:
        # Step 1: AI 分類圖像類型
        image_type = await with_gemini_retry_async(
            "圖像類型分類",
            _classify_image_type,
            question.image_description,
            error_type=RuntimeError
        )
        
        logger.info(f"[Visualizer] 圖像類型分類結果: {image_type}")
        
        success = False
        
        # Step 2: 根據分類結果選擇生成方式
        if image_type == "chart":
            # 使用 Matplotlib 生成統計圖表
            logger.info(f"[Visualizer] 使用 Matplotlib 生成圖表")
            success = await with_gemini_retry_async(
                "Matplotlib 圖表生成",
                _generate_chart_with_matplotlib,
                question.image_description,
                output_path,
                model_name,
                error_type=RuntimeError
            )
        else:
            # 使用 Gemini 圖像生成 API 生成插圖
            logger.info(f"[Visualizer] 使用 Gemini 圖像 API 生成插圖")
            success = await with_gemini_retry_async(
                "Gemini 圖像生成",
                _generate_image_with_gemini,
                question.image_description,
                output_path,
                error_type=RuntimeError
            )
        
        if success and os.path.exists(output_path):
            logger.info(f"[Visualizer] 圖像生成成功: {relative_path}")
            return relative_path
        else:
            logger.warning(f"[Visualizer] 圖像生成失敗或文件不存在: {output_path}")
            return None
            
    except Exception as e:
        logger.error(f"[Visualizer] 生成圖像時發生錯誤: {e}")
        return None


async def visualizer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Visualizer Node - 生成題目所需的圖像
    
    支援兩種生成方式：
    - 統計圖表：使用 Matplotlib 生成（柱狀圖、折線圖、餅圖等）
    - 非圖表插圖：使用 Gemini 圖像生成 API（示意圖、概念圖等）
    
    輸入 State:
        - questions: 題目列表（部分可能有 image_description）
        - exam_id: 考試 ID
    
    輸出 State 更新:
        - questions: 更新後的題目列表（包含 image_path）
        - images: 圖像路徑映射
    """
    questions: List[ExamQuestion] = state.get("questions", [])
    exam_id = state.get("exam_id", "exam_unknown")
    
    # 找出需要生成圖像的題目
    questions_with_images = [q for q in questions if q.image_description]
    
    if not questions_with_images:
        logger.info("[Visualizer] 沒有需要生成圖像的題目，跳過")
        return {
            **state,
            "images": {}
        }
    
    logger.info(f"[Visualizer] 需要生成 {len(questions_with_images)} 個圖像")
    
    settings = get_settings()
    model_name = settings.google_ai_model or "gemini-2.5-flash"
    
    # 依序生成圖像
    images: Dict[str, str] = {}
    updated_questions: List[ExamQuestion] = []
    
    for question in questions:
        if question.image_description:
            # 生成圖像
            image_path = await _generate_single_image(question, exam_id, model_name)
            
            if image_path:
                # 更新題目的 image_path
                question.image_path = image_path
                images[question.question_id] = image_path
        
        updated_questions.append(question)
    
    logger.info(f"[Visualizer] 圖像生成完成 - 成功: {len(images)}/{len(questions_with_images)}")
    
    return {
        **state,
        "questions": updated_questions,
        "images": images
    }

