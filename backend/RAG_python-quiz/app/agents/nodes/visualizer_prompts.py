# -*- coding: utf-8 -*-
"""Prompt builders and schemas for visualizer image generation."""


def build_classification_prompt(description: str) -> str:
    return f"""Please analyze the following image description and determine if it is a "Statistical Chart" or a "Non-Chart Illustration".

## Image Description
{description}

## Classification Criteria
- **chart** (Statistical Chart): Bar chart, line chart, pie chart, scatter plot, histogram, area chart, radar chart, etc., that can be visualized using Matplotlib.
- **illustration** (Non-Chart Illustration): Diagram, concept map, flowchart, architecture diagram, scene illustration, object icon, etc., that requires drawing specific graphics.
"""


def build_classification_schema() -> dict:
    return {
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


def build_code_generation_prompt(image_description: str, output_path: str) -> str:
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


def build_image_prompt_transform_prompt(description: str) -> str:
    return f"""You are a professional AI image generation prompt engineer. Please convert the following image description into a prompt suitable for an AI image generation model.

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
