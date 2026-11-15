"""Two kiosk accounts. An admin may enroll. A user may only be verified."""

import base64
import hashlib
import hmac
import os
import time

TOKEN_TTL_SECONDS = 8 * 60 * 60


def _secret() -> str:
    return os.getenv("ACCOUNT_TOKEN_SECRET", "hid-demo-token-secret")


def _same(left: str, right: str) -> bool:
    left_bytes = left.encode()
    right_bytes = right.encode()
    if len(left_bytes) != len(right_bytes):
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def accounts() -> dict[str, dict[str, str]]:
    return {
        "admin": {
            "password": os.getenv("ADMIN_PASSWORD", "admin"),
            "role": "admin",
        },
        "user": {
            "password": os.getenv("USER_PASSWORD", "user"),
            "role": "user",
        },
    }


def authenticate(username: str, password: str) -> str | None:
    account = accounts().get(username)
    if account is None or not _same(account["password"], password):
        return None
    return account["role"]


def issue_token(username: str, role: str, now: int | None = None) -> str:
    if role not in ("admin", "user"):
        raise ValueError("Unknown role")
    expires_at = (int(time.time()) if now is None else now) + TOKEN_TTL_SECONDS
    payload = f"{username}|{role}|{expires_at}"
    signature = hmac.new(
        _secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()


def read_token(token: str, now: int | None = None) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, role, expires_at, signature = raw.split("|")
        payload = f"{username}|{role}|{expires_at}"
        expected = hmac.new(
            _secret().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not _same(signature, expected):
            raise ValueError
        if int(expires_at) <= (int(time.time()) if now is None else now):
            raise ValueError
        if role not in ("admin", "user") or not username:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("Sign in required") from None
    return username, role
