"""Mock Banking API: a separate application the AltCredit platform calls with an API key.

Simulates a partner bank's pre-approval and application endpoints for the demo.
It is NOT connected to any real bank, stores only pseudonymous references, and
receives no personal data (no name, phone or address).

Run:  MOCKBANK_API_KEY=... uvicorn mockbank.app:app --port 8001
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB = Path(os.environ.get("MOCKBANK_DB", Path(__file__).resolve().parent / "data" / "bank.db"))
API_KEY = os.environ.get("MOCKBANK_API_KEY")
REVIEW_SECONDS = float(os.environ.get("MOCKBANK_REVIEW_SECONDS", "8"))

app = FastAPI(title="Mock Partner Bank API", version="1.0.0",
              description="Simulated banking system for the AltCredit prototype. Synthetic data only.")


def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS preapprovals (id TEXT PRIMARY KEY, applicant_ref TEXT, product_id TEXT, status TEXT,
                   limit_amount REAL, rate REAL, created REAL, valid_until TEXT, payload TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, preapproval_id TEXT, applicant_ref TEXT, product_id TEXT,
                   final_status TEXT, created REAL, account_ref TEXT)""")
    return con


def require_key(x_api_key: str | None = Header(default=None)):
    if not API_KEY:
        raise HTTPException(503, "bank API key not configured (set MOCKBANK_API_KEY)")
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, "invalid API key")


class PreapprovalIn(BaseModel):
    applicant_ref: str = Field(..., description="Pseudonymous applicant reference (no PII)")
    product_id: str
    product_type: str
    min_score: int
    policy_score: int = Field(..., ge=0, le=1000)
    risk_tier: str
    review_flag: str = "NONE"
    requested_amount: float | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    rate: float | None = None


class ApplyIn(BaseModel):
    preapproval_id: str


@app.get("/bank/health")
def health():
    return {"status": "ok", "bank": "Mock Partner Bank", "synthetic": True}


@app.post("/bank/preapproval", dependencies=[Depends(require_key)])
def preapproval(body: PreapprovalIn):
    if body.policy_score < body.min_score:
        status, limit = "DECLINED", 0.0
    elif body.review_flag == "ENHANCED_REVIEW":
        status, limit = "REFERRED", body.amount_min or 0.0
    else:
        status = "PRE_APPROVED"
        lo, hi = body.amount_min or 0, body.amount_max or 0
        span = max(hi - lo, 0)
        frac = min(max((body.policy_score - body.min_score) / max(1000 - body.min_score, 1), 0), 1)
        limit = round((lo + span * frac) / 500) * 500
        if body.requested_amount:
            limit = min(limit, body.requested_amount) if limit else body.requested_amount
    pid = "PA-" + uuid.uuid4().hex[:8].upper()
    valid = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    con = db()
    con.execute("INSERT INTO preapprovals VALUES (?,?,?,?,?,?,?,?,?)", (pid, body.applicant_ref, body.product_id, status, limit,
                                                                        body.rate, time.time(), valid, body.model_dump_json()))
    con.commit()
    return {"preapproval_id": pid, "status": status, "indicative_limit": limit, "rate": body.rate, "valid_until": valid,
            "message": {"PRE_APPROVED": "Pre-approved on the AltCredit policy score.",
                        "REFERRED": "Referred to an underwriter: AltCredit flagged this applicant for enhanced review.",
                        "DECLINED": "Policy score below the product minimum."}[status]}


@app.post("/bank/apply", dependencies=[Depends(require_key)])
def apply(body: ApplyIn):
    con = db()
    pa = con.execute("SELECT * FROM preapprovals WHERE id=?", (body.preapproval_id,)).fetchone()
    if not pa:
        raise HTTPException(404, "pre-approval not found")
    if pa["status"] == "DECLINED":
        raise HTTPException(409, "pre-approval was declined")
    app_id = "BNK-" + uuid.uuid4().hex[:10].upper()
    final = "APPROVED" if pa["status"] == "PRE_APPROVED" else "MANUAL_REVIEW"
    con.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?)", (app_id, pa["id"], pa["applicant_ref"], pa["product_id"], final,
                                                                   time.time(), "XXXX" + str(uuid.uuid4().int)[-4:]))
    con.commit()
    return {"application_id": app_id, "status": "SUBMITTED", "product_id": pa["product_id"]}


@app.get("/bank/application/{application_id}", dependencies=[Depends(require_key)])
def application(application_id: str):
    con = db()
    a = con.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
    if not a:
        raise HTTPException(404, "application not found")
    age = time.time() - a["created"]
    if age < REVIEW_SECONDS / 2:
        status, note = "SUBMITTED", "Application received."
    elif age < REVIEW_SECONDS:
        status, note = "UNDER_REVIEW", "Documents and policy decision under review."
    else:
        status = a["final_status"]
        note = {"APPROVED": f"Approved. Account {a['account_ref']} opened (synthetic).",
                "MANUAL_REVIEW": "An underwriter will contact you through AltCredit."}[status]
    return {"application_id": a["id"], "product_id": a["product_id"], "status": status, "note": note,
            "account_ref": a["account_ref"] if status == "APPROVED" else None}
