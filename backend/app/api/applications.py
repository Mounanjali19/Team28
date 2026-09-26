"""Apply for a product through the mock partner bank (AltCredit -> Bank API -> status)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.bank import client as bank
from app.database.db import audit, get_conn, now_iso, one, rows
from app.schemas import ApplicationIn
from app.security.auth import require_role
from app.services import build_profile

router = APIRouter(prefix="/api/applications", tags=["bank integration"])


@router.post("", summary="Request pre-approval and submit an application to the partner bank")
def apply(body: ApplicationIn, p: dict = Depends(require_role("user"))):
    con = get_conn()
    uid = p["user_id"]
    prof = build_profile(con, uid)
    prod = next((x for x in prof["products"] if x["product_id"] == body.product_id), None)
    if not prod:
        raise HTTPException(404, "unknown product")
    if not prod["eligible"]:
        raise HTTPException(409, f"not eligible: {prod['reason']}")
    offer = None
    if body.offer_id:
        offer = one(con, "SELECT * FROM offers WHERE offer_id=? AND user_id=?", (body.offer_id, uid))
        if not offer or offer["status"] != "accepted":
            raise HTTPException(409, "accept the offer before applying")
    payload = {"applicant_ref": bank.applicant_ref(uid), "product_id": prod["product_id"], "product_type": prod["type"],
               "min_score": prod["min_score"], "policy_score": prof["policy"]["score"], "risk_tier": prof["policy"]["tier"]["code"],
               "review_flag": prof["ml"].get("agreement", {}).get("review_flag", "NONE"),
               "requested_amount": body.requested_amount or (offer["amount"] if offer else None),
               "amount_min": prod["amount_min"], "amount_max": prod["amount_max"],
               "rate": offer["interest_rate"] if offer else prod["interest_rate_pct"]}
    try:
        pre = bank.preapproval(payload)
        sub = bank.apply(pre["preapproval_id"]) if pre["status"] != "DECLINED" else None
    except bank.BankUnavailable as e:
        raise HTTPException(503, str(e))
    status = sub["status"] if sub else "DECLINED"
    cur = con.execute("""INSERT INTO bank_applications (user_id, product_id, offer_id, bank_reference, status, preapproval_id, created_at,
                         updated_at, response_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                      (uid, prod["product_id"], body.offer_id, sub["application_id"] if sub else None, status, pre["preapproval_id"],
                       now_iso(), now_iso(), json.dumps({"preapproval": pre, "submission": sub, "sent_payload": payload})))
    audit(con, "bank_application", p["sub"], "bank_application", str(cur.lastrowid),
          {"product_id": prod["product_id"], "preapproval": pre["status"], "bank_reference": sub and sub["application_id"]})
    con.commit()
    return {"id": cur.lastrowid, "status": status, "preapproval": pre, "submission": sub, "sent_to_bank": payload,
            "flow": ["AltCredit policy decision", "POST /bank/preapproval", "POST /bank/apply", "GET /bank/application/{id}"]}


@router.get("", summary="This user's bank applications")
def mine(p: dict = Depends(require_role("user"))):
    return rows(get_conn(), """SELECT a.*, pr.product_name FROM bank_applications a JOIN products pr USING (product_id)
                               WHERE a.user_id=? ORDER BY a.id DESC""", (p["user_id"],))


@router.get("/{app_id}", summary="Refresh an application's status from the bank")
def status(app_id: int, p: dict = Depends(require_role("user"))):
    con = get_conn()
    a = one(con, "SELECT * FROM bank_applications WHERE id=? AND user_id=?", (app_id, p["user_id"]))
    if not a:
        raise HTTPException(404, "application not found")
    if a["bank_reference"]:
        try:
            s = bank.status(a["bank_reference"])
        except bank.BankUnavailable as e:
            raise HTTPException(503, str(e))
        if s["status"] != a["status"]:
            con.execute("UPDATE bank_applications SET status=?, updated_at=? WHERE id=?", (s["status"], now_iso(), app_id))
            audit(con, "bank_status", "bank", "bank_application", str(app_id), s)
            con.commit()
        a = one(con, "SELECT * FROM bank_applications WHERE id=?", (app_id,))
        a["bank"] = s
    return a
