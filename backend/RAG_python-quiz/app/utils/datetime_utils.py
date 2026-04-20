# -*- coding: utf-8 -*-
from typing import Optional
from datetime import datetime


def iso(ts: Optional[datetime]) -> Optional[str]:
    """
    將 datetime 物件轉換為 ISO 格式字符串
    
    Args:
        ts: datetime 物件或 None
        
    Returns:
        ISO 格式字符串或 None
    """
    return ts.isoformat() if ts else None

