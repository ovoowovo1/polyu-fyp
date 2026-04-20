# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional, Sequence
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
import json as json_lib
import bcrypt

from app.services.pg_db import _get_conn
from app.logger import get_logger
from app.utils.jwt_utils import create_session_token, verify_token

logger = get_logger(__name__)




def login(email: str, password: str, role: Optional[str] = None) -> Dict[str, Any]:
    """
    用戶登入，驗證憑證後創建 JWT session token（無需 sessions 表）
    
    Args:
        email: 用戶郵箱
        password: 明文密碼
        
    Returns:
        Dict containing message, user info, and session_token (JWT) if successful
        Raises ValueError if login failed
    """
    with _get_conn() as conn, conn.cursor() as cur:
        # 根據 email 查詢用戶
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        
        if not row:
            logger.warning(f"Login failed for email: {email} - user not found")
            raise ValueError("Invalid email or password")
        
        # 驗證密碼
        password_hash = row.get("password_hash")
        if not password_hash or not _verify_password(password, password_hash):
            logger.warning(f"Login failed for email: {email} - invalid password")
            raise ValueError("Invalid email or password")

        # 如果前端帶入 role，檢查資料庫中的 role 是否一致
        db_role = row.get("role")
        if role is not None:
            if role not in ("teacher", "student"):
                logger.warning(f"Login failed for email: {email} - invalid requested role: {role}")
                raise ValueError("Invalid role requested")
            if db_role != role:
                logger.warning(f"Login failed for email: {email} - role mismatch (requested: {role}, actual: {db_role})")
                raise ValueError("Role does not match")
        
        user_id = row.get("id")
        if not user_id:
            logger.error(f"User record missing ID for email: {email}")
            raise ValueError("User record is invalid")
        
        # 更新最後登入時間
        cur.execute(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (datetime.now(timezone.utc), user_id)
        )
        conn.commit()
        
        # 生成 JWT session token（無狀態，不需要存儲到數據庫）
        # 使用 email 作為 username，因為 JWT 中通常包含可識別的用戶信息
        session_token = create_session_token(
            user_id=str(user_id),  # UUID 轉換為字符串
            username=email,
            expires_in_days=7  # Session 有效期設為 7 天（可根據需求調整）
        )
        
        logger.info(f"Session token created for user: {email} (user_id: {user_id})")
        
        # 構建用戶信息（不包含密碼哈希）
        user_info = dict(row)
        user_info.pop("password_hash", None)  # 移除密碼哈希，不要返回給前端
        
        return {
            "message": "Login successful",
            "user": user_info,
            "session_token": session_token
        }

def verify_session(session_token: str) -> Optional[Dict[str, Any]]:
    """
    驗證 JWT session token 是否有效（無需查詢數據庫）
    
    Args:
        session_token: 要驗證的 JWT session token
        
    Returns:
        如果有效，返回包含 user_id (UUID) 和 email 的字典
        如果無效或已過期，返回 None
    """
    payload = verify_token(session_token)
    if payload:
        return {
            "user_id": payload.get("sub"),  # UUID 字符串
            "email": payload.get("username"),  # JWT 中的 username 實際存儲的是 email
            "exp": payload.get("exp"),
            "iat": payload.get("iat")
        }
    return None


def logout(session_token: str) -> Dict[str, Any]:
    """
    登出用戶（JWT 是無狀態的，客戶端只需要丟棄 token 即可）
    
    注意：JWT 無法主動撤銷，但由於是無狀態設計，前端丟棄 token 即可
    如果需要強制撤銷功能，需要額外實現黑名單機制
    
    Args:
        session_token: JWT session token（實際上不需要用於撤銷）
        
    Returns:
        Dict with message indicating success
    """
    # 驗證 token 是否有效（可選，用於日誌記錄）
    payload = verify_token(session_token)
    if payload:
        logger.info(f"User logout requested for user_id: {payload.get('sub')}")
    else:
        logger.warning(f"Logout attempted with invalid token")
    
    return {"message": "Logout successful. Please discard the token on client side."}


def register(email: str, password: str, full_name: str, role: str) -> Dict[str, Any]:
    """
    用戶註冊
    
    Args:
        email: 用戶郵箱
        password: 明文密碼（注意：bcrypt 限制密碼不能超過 72 字節）
        full_name: 用戶全名
        role: 用戶角色 ('teacher' 或 'student')
        
    Returns:
        Dict containing message and user info if successful
        Raises ValueError if registration failed
    """
    # 驗證 role
    if role not in ('teacher', 'student'):
        raise ValueError(f"Invalid role: {role}. Must be 'teacher' or 'student'")
    
    # 驗證密碼長度（bcrypt 限制為 72 字節）
    password_bytes = password.encode('utf-8')

    
    with _get_conn() as conn, conn.cursor() as cur:
        # 檢查 email 是否已存在
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"Email {email} is already registered")
        
        # 哈希密碼（會自動處理超過 72 字節的情況）
        password_hash = _hash_password(password)
        
        # 插入用戶記錄
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id, email, full_name, role, created_at
        """, (email, password_hash, full_name, role))
        
        user_row = cur.fetchone()
        user_id = user_row["id"]
        
        # 根據 role 插入對應的子表記錄
        if role == 'teacher':
            cur.execute("INSERT INTO teachers (user_id) VALUES (%s)", (user_id,))
        elif role == 'student':
            cur.execute("INSERT INTO students (user_id) VALUES (%s)", (user_id,))
        
        conn.commit()
        
        logger.info(f"User registered: {email} (role: {role}, user_id: {user_id})")
        
        return {
            "message": "Registration successful",
            "user": dict(user_row)
        }


def _hash_password(password: str) -> str:
    """使用 bcrypt 將明文密碼轉為雜湊字串"""
    if not isinstance(password, str):
        raise TypeError("Password must be a string")

    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """驗證明文密碼是否與儲存的 bcrypt 雜湊相符"""
    if not isinstance(password, str):
        return False

    try:
        password_hash_bytes = (
            password_hash.encode("utf-8") if isinstance(password_hash, str) else password_hash
        )
        return bcrypt.checkpw(password.encode("utf-8"), password_hash_bytes)
    except ValueError as exc:
        logger.error("Failed to verify password: %s", exc)
        return False