#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
創建測試用戶腳本
改為透過 FastAPI /auth/register 端點建立帳號
"""
import os
import sys
from typing import Any, Dict

import requests

from app.config import get_settings
from app.logger import get_logger


logger = get_logger(__name__)

settings = get_settings()
DEFAULT_BASE_URL = f"http://localhost:{settings.port}"
API_BASE_URL = os.getenv("API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
REGISTER_ENDPOINT = f"{API_BASE_URL}/auth/register"

try:
    DEFAULT_TIMEOUT = float(os.getenv("API_TIMEOUT", "15"))
except ValueError:
    DEFAULT_TIMEOUT = 15.0


def _build_error_message(data: Any, fallback_text: str, status_code: int) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, dict):
            return detail.get("error") or detail.get("message") or str(detail)
        if detail:
            return str(detail)
        for key in ("error", "message"):
            value = data.get(key)
            if value:
                return str(value)
    if fallback_text:
        return fallback_text.strip()
    return f"HTTP {status_code}"


def _post_register(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        REGISTER_ENDPOINT,
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        data: Any = response.json()
    except ValueError:
        data = None

    if response.ok:
        if isinstance(data, dict):
            return data
        raise RuntimeError("註冊成功但回應格式非 JSON 物件")

    message = _build_error_message(data, response.text, response.status_code)
    if response.status_code in (400, 409):
        raise ValueError(message)
    raise RuntimeError(message)


def create_test_users():
    """透過 API 建立測試用戶"""
    users = [
        {
            "email": "s1@example.com",
            "password": "12345678",
            "full_name": "Student One",
            "role": "student",
        },
        {
            "email": "s2@example.com",
            "password": "12345678",
            "full_name": "Student Two",
            "role": "student",
        },
        {
            "email": "s3@example.com",
            "password": "12345678",
            "full_name": "Student Three",
            "role": "student",
        },
        {
            "email": "t1@example.com",
            "password": "12345678",
            "full_name": "Teacher One",
            "role": "teacher",
        },
    ]

    print("Creating test users via API...")
    print(f"Target endpoint: {REGISTER_ENDPOINT}")
    print("-" * 50)

    for user in users:
        payload = {
            "email": user["email"],
            "password": user["password"],
            "full_name": user["full_name"],
            "role": user["role"],
        }

        try:
            result = _post_register(payload)
            print(f"[OK] Created {user['role']}: {user['email']}")
            print(f"  Full Name: {result['user']['full_name']}")
            print(f"  Role: {result['user']['role']}")
            print(f"  ID: {result['user']['id']}")
        except ValueError as e:
            message = str(e)
            if "already" in message.lower():
                print(f"[SKIP] {user['email']} already exists, skipping")
            else:
                print(f"[ERROR] Failed to create {user['email']}: {message}")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Network error creating {user['email']}: {str(e)}")
        except Exception as e:
            print(f"[ERROR] Error creating {user['email']}: {str(e)}")
        print()

    print("-" * 50)
    print("Done!")
    print("\nTest accounts:")
    print("Student: s1@example.com / 12345678")
    print("Teacher: t1@example.com / 12345678")


if __name__ == "__main__":
    try:
        create_test_users()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n發生錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

