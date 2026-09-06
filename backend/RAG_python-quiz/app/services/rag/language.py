"""Planner-owned language policy; the backend never classifies natural language."""
from contextvars import ContextVar
import json

answer_language = ContextVar("rag_answer_language", default=None)
system_messages = ContextVar("rag_system_messages", default=None)

# Last-resort service notices when the planner itself is unavailable.
DEFAULT_NOTICES = {
    "insufficient_evidence": "The selected documents do not contain sufficient evidence.",
    "verification_unavailable": "Verification could not be completed. Please retry.",
    "omitted_content": "Some content could not be verified from the selected documents and was omitted.",
}


def language_for(question: str):
    return answer_language.get()


def instruction(question: str) -> str:
    target = answer_language.get()
    policy = ("Required answer language (planner data): " + json.dumps(target, ensure_ascii=False)
              if target else "Determine the answer language from the original question: obey any explicit language request; otherwise follow the question language.")
    return (policy + ". Use this language for all explanatory prose, headings, limitations, verification "
            "reasons and missing topics. For Chinese use Traditional Chinese. Document and UI language "
            "do not override the user's request. Preserve source quotations, code and technical names.")


def notice(name: str) -> str:
    return (system_messages.get() or {}).get(name) or DEFAULT_NOTICES[name]
