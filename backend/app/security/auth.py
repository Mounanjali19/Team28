"""Demo authentication: PBKDF2 password hashes and HMAC-signed bearer tokens.

Deliberately small (no OAuth, no refresh tokens). The signing key comes from
ALTCREDIT_SECRET_KEY; nothing secret is stored in code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.database.db import get_conn, one

_ITER = 120_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except ValueError:
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(claims: dict) -> str:
    body = dict(claims, exp=int(time.time()) + settings.token_ttl_minutes * 60)
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> dict:
    try:
        payload, sig = token.split(".")
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token")
    expect = _b64(hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    claims = json.loads(_unb64(payload))
    if claims.get("exp", 0) < time.time():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    return claims


def authenticate(username: str, password: str) -> dict | None:
    acc = one(get_conn(), "SELECT * FROM auth_accounts WHERE username=?", (username,))
    if not acc or not verify_password(password, acc["password_hash"]):
        return None
    return acc


def current_principal(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    return read_token(cred.credentials)


def require_role(*roles):
    def dep(p: dict = Depends(current_principal)) -> dict:
        if p.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {roles}")
        return p
    return dep


def assert_user_access(principal: dict, user_id: str):
    """Users see only themselves; lenders and admins may view candidates (masked elsewhere)."""
    if principal["role"] == "user" and principal.get("user_id") != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you can only access your own profile")
