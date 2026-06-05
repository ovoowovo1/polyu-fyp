from datetime import datetime


def iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None
