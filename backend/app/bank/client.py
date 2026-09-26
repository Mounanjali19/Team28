"""Client for the mock partner bank (separate application, API-key protected)."""
from __future__ import annotations

import hashlib

import httpx

from app.config import settings


class BankUnavailable(RuntimeError):
    pass


def applicant_ref(user_id: str) -> str:
    """Pseudonymous reference: the bank never receives the user id or any PII."""
    return "AC-" + hashlib.sha256((settings.secret_key + user_id).encode()).hexdigest()[:12].upper()


_transport: httpx.BaseTransport | None = None   # tests inject an ASGI transport here


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.bank_api_url, timeout=5.0, transport=_transport,
                        headers={"X-API-Key": settings.bank_api_key})


def _call(method: str, path: str, **kw) -> dict:
    if not settings.bank_api_key:
        raise BankUnavailable("bank API key not configured (ALTCREDIT_BANK_API_KEY)")
    try:
        with _client() as c:
            r = c.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise BankUnavailable(f"bank API unreachable at {settings.bank_api_url}: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        raise BankUnavailable(f"bank API error {r.status_code}: {r.text[:200]}")
    return r.json()


def preapproval(payload: dict) -> dict:
    return _call("POST", "/bank/preapproval", json=payload)


def apply(preapproval_id: str) -> dict:
    return _call("POST", "/bank/apply", json={"preapproval_id": preapproval_id})


def status(application_id: str) -> dict:
    return _call("GET", f"/bank/application/{application_id}")
