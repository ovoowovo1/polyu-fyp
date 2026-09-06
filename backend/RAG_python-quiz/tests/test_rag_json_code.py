import json

from app.services.ai.llm.structured_json import _parse_structured_json_text


def test_embedded_code_fences_survive_json_parsing_and_outer_json_fences():
    value = {"blocks": [{"id": "code-1", "markdown": "```python\nfor item in items:\n    print(item)\n```"}]}
    encoded = json.dumps(value)
    assert _parse_structured_json_text(encoded, "RAG") == value
    assert _parse_structured_json_text("```json\n" + encoded + "\n```", "RAG") == value
