from __future__ import annotations

from typing import Any, Dict, Optional
import json


_RAW_PREVIEW_LIMIT = 400


def _compact_text(value: Any, limit: int = _RAW_PREVIEW_LIMIT) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = repr(value)
    else:
        text = str(value)

    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


class EmbeddingProviderError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        provider: str,
        model: str,
        base_url: str,
        http_status: Optional[int] = None,
        upstream_code: Optional[Any] = None,
        upstream_message: Optional[str] = None,
        raw_preview: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.http_status = http_status
        self.upstream_code = upstream_code
        self.upstream_message = upstream_message
        self.raw_preview = _compact_text(raw_preview)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "http_status": self.http_status,
            "upstream_code": self.upstream_code,
            "upstream_message": self.upstream_message,
            "raw_preview": self.raw_preview,
        }


class DocumentIngestError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = _compact_text(details)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload
