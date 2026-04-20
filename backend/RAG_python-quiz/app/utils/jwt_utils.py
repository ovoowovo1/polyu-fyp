# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)

_http_bearer = HTTPBearer(auto_error=False)

def create_session_token(user_id: str, username: str, expires_in_days: int = 7) -> str:
    """
    創建 JWT session token
    
    Args:
        user_id: 用戶 ID (UUID 字符串)
        username: 用戶名 (實際存儲的是 email)
        expires_in_days: token 有效期（天數），預設 7 天
        
    Returns:
        JWT token 字符串
    """
    settings = get_settings()
    secret_key = settings.jwt_secret_key
    
    # 計算過期時間
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    
    # 構建 payload
    payload = {
        "sub": str(user_id),  # subject (user ID - UUID 字符串)
        "username": username,  # 實際存儲 email
        "iat": datetime.utcnow(),  # issued at
        "exp": expires_at,  # expiration time
        "type": "session"
    }
    
    # 生成 token
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    logger.debug(f"Created session token for user_id: {user_id}")
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    驗證 JWT token 是否有效
    
    Args:
        token: JWT token 字符串
        
    Returns:
        如果有效，返回解碼後的 payload (包含 user_id, username 等)
        如果無效或已過期，返回 None
    """
    settings = get_settings()
    secret_key = settings.jwt_secret_key
    
    try:
        # 解碼並驗證 token
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        logger.debug(f"Token verified for user_id: {payload.get('sub')}")
        return payload
    except JWTError as e:
        logger.warning(f"Token verification failed: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {str(e)}", exc_info=True)
        return None


def get_user_id_from_token(token: str) -> Optional[str]:
    """
    從 token 中提取 user_id
    
    Args:
        token: JWT token 字符串
        
    Returns:
        如果有效，返回 user_id (UUID 字符串)
        如果無效，返回 None
    """
    payload = verify_token(token)
    if payload and "sub" in payload:
        return str(payload["sub"])  # UUID 字符串
    return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> Dict[str, Any]:
    """
    FastAPI 依賴：驗證 Authorization Bearer token 並回傳 payload。
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail={"error": "Authorization header missing"})

    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail={"error": "Invalid or expired token"})

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail={"error": "Invalid token payload"})

    return {
        "token": token,
        "user_id": str(user_id),
        "email": payload.get("username"),
        "payload": payload,
    }

