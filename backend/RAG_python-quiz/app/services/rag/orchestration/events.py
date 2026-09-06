from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_event(message: str, data: Any = None, event_type: str = "progress") -> Dict[str, Any]:
    return {
        "type": event_type,
        "message": message,
        "data": data,
        "timestamp": utc_now(),
    }
