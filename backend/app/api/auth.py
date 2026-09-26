"""Authentication and self-service onboarding (profile creation + statement upload)."""
from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.database.db import audit, get_conn, now_iso, one, rows
from app.ingestion.pipeline import ingest_upload, parse_uploaded_table
from app.schemas import DemoLoginIn, LoginIn
from app.security.auth import authenticate, current_principal, hash_password, issue_token
from app.services import build_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])
DEMO_MODE = os.environ.get("ALTCREDIT_DEMO_MODE", "1") == "1"


def _session(acc: dict) -> dict:
    claims = {"sub": acc["username"], "role": acc["role"], "user_id": acc["user_id"], "lender_id": acc["lender_id"]}
    return {"token": issue_token(claims), "role": acc["role"], "username": acc["username"], "user_id": acc["user_id"],
            "lender_id": acc["lender_id"], "display_name": acc["display_name"]}


@router.post("/login")
def login(body: LoginIn):
    acc = authenticate(body.username.strip(), body.password)
    if not acc:
        raise HTTPException(401, "invalid username or password")
    con = get_conn()
    audit(con, "login", acc["username"], "auth", acc["username"], {"role": acc["role"]})
    con.commit()
    return _session(acc)


@router.post("/demo-login", summary="One-click login for seeded demo accounts (only when ALTCREDIT_DEMO_MODE=1)")
def demo_login(body: DemoLoginIn):
    if not DEMO_MODE:
        raise HTTPException(403, "demo login disabled")
    con = get_conn()
    acc = one(con, "SELECT * FROM auth_accounts WHERE username=?", (body.username,))
    if not acc or not (acc["username"].startswith("demo.") or acc["role"] == "lender"):
        raise HTTPException(404, "not a demo account")
    audit(con, "demo_login", acc["username"], "auth", acc["username"], {"role": acc["role"]})
    con.commit()
    return _session(acc)


@router.get("/demo-accounts")
def demo_accounts():
    con = get_conn()
    users = rows(con, """SELECT a.username, a.display_name, a.user_id, u.demo_label, s.score, s.tier
                         FROM auth_accounts a JOIN users u ON u.user_id=a.user_id
                         LEFT JOIN scores s ON s.user_id=a.user_id AND s.is_current=1
                         WHERE a.role='user' AND a.username LIKE 'demo.%' ORDER BY s.score DESC""")
    lenders = rows(con, """SELECT a.username, a.display_name, a.lender_id,
                           (SELECT COUNT(*) FROM products p WHERE p.lender_id=a.lender_id) AS n_products
                           FROM auth_accounts a WHERE a.role='lender' ORDER BY n_products DESC, a.username""")
    return {"demo_mode": DEMO_MODE, "users": users, "lenders": lenders,
            "note": "Seeded synthetic accounts. Password is set by ALTCREDIT_DEMO_PASSWORD at seed time (see README)."}


@router.get("/me")
def me(p: dict = Depends(current_principal)):
    acc = one(get_conn(), "SELECT username, role, user_id, lender_id, display_name FROM auth_accounts WHERE username=?", (p["sub"],))
    if not acc:
        raise HTTPException(401, "account no longer exists")
    return acc


@router.post("/register", summary="Create a user profile and upload transactions (CSV/JSON); the rule engine scores it immediately")
async def register(username: str = Form(..., min_length=3, max_length=40), password: str = Form(..., min_length=8),
                   profile: str = Form(..., description="JSON: age, education_level, employment_status, monthly_income, city_tier, "
                                                        "housing_status, months_in_current_job, months_at_address, monthly_rent, display_name"),
                   transactions: UploadFile = File(...), bills: UploadFile | None = File(default=None)):
    con = get_conn()
    if one(con, "SELECT 1 AS x FROM auth_accounts WHERE username=?", (username,)):
        raise HTTPException(409, "username already taken")
    try:
        prof = json.loads(profile)
        txn = parse_uploaded_table(await transactions.read(), transactions.filename or "upload.csv")
        bl = parse_uploaded_table(await bills.read(), bills.filename or "bills.csv") if bills is not None else None
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"could not read upload: {e}")
    if txn.empty:
        raise HTTPException(422, "transaction file is empty")
    user_id = "USR_N" + uuid.uuid4().hex[:6].upper()
    try:
        result = ingest_upload(con, user_id, prof, txn, bl)
    except ValueError as e:
        con.rollback()
        raise HTTPException(422, str(e))
    con.execute("INSERT INTO auth_accounts VALUES (?,?,?,?,?,?,?)", (username, hash_password(password), "user", user_id, None,
                                                                    prof.get("display_name") or username, now_iso()))
    con.commit()
    profile_out = build_profile(con, user_id, persist=True, trigger="onboarding", actor=username)
    acc = one(con, "SELECT * FROM auth_accounts WHERE username=?", (username,))
    return {"session": _session(acc), "ingestion": result, "score": profile_out["policy"]["score"],
            "tier": profile_out["policy"]["tier"], "timing_ms": profile_out["timing_ms"]}
