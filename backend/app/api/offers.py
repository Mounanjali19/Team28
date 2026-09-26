"""Offer endpoints: lenders push offers (single or campaign); users view, accept, reject."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.offers_logic import check_push, contact_for, create_offer, respond
from app.database.db import get_conn, now_iso, one, rows
from app.schemas import BulkOfferIn, OfferIn, OfferResponseIn
from app.security.auth import assert_user_access, current_principal, require_role
from app.services import build_profile, current_score_row, invalidate

router = APIRouter(prefix="/api", tags=["offers"])


def _offer_view(o: dict) -> dict:
    return o


@router.get("/users/{user_id}/offers", summary="Offers pushed to this applicant")
def user_offers(user_id: str, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    con = get_conn()
    con.execute("UPDATE offers SET status='expired' WHERE user_id=? AND status IN ('sent','viewed') AND expires_at < ?", (user_id, now_iso()))
    con.commit()
    return rows(con, """SELECT o.*, p.product_name, p.type AS product_type, p.min_score, l.lender_name
                        FROM offers o JOIN products p USING (product_id) JOIN lenders l ON l.lender_id=o.lender_id
                        WHERE o.user_id=? ORDER BY o.created_at DESC""", (user_id,))


@router.post("/offers", summary="Lender pushes one offer to a qualifying candidate (LP-05/06/08)")
def push_offer(body: OfferIn, p: dict = Depends(require_role("lender"))):
    con = get_conn()
    prop = _propensity(con, body.user_id, body.product_id)
    try:
        o = create_offer(con, p["lender_id"], body.user_id, body.product_id, body.interest_rate, body.amount, body.message,
                         actor=p["sub"], expiry_days=body.expiry_days, propensity=prop)
    except ValueError as e:
        con.rollback()
        raise HTTPException(422, str(e))
    con.commit()
    return o


def _propensity(con, user_id, product_id):
    r = one(con, "SELECT detail_json FROM ml_predictions WHERE user_id=? AND is_current=1", (user_id,))
    if not r:
        return None
    return json.loads(r["detail_json"]).get("propensity", {}).get(product_id)


@router.post("/offers/bulk", summary="Campaign: push one product to many candidates; non-qualifiers are skipped with a reason")
def push_bulk(body: BulkOfferIn, p: dict = Depends(require_role("lender"))):
    con = get_conn()
    cid = "CMP_" + uuid.uuid4().hex[:8].upper()
    sent, skipped = [], []
    for uid in dict.fromkeys(body.user_ids):
        ok, reason, _, _ = check_push(con, p["lender_id"], uid, body.product_id)
        if not ok:
            skipped.append({"user_id": uid, "reason": reason})
            continue
        dq = one(con, "SELECT data_quality FROM scores WHERE user_id=? AND is_current=1", (uid,))
        if dq and dq["data_quality"] == "POOR":
            skipped.append({"user_id": uid, "reason": "data quality POOR: excluded from bulk push, review individually (LP-08)"})
            continue
        o = create_offer(con, p["lender_id"], uid, body.product_id, body.interest_rate, body.amount, body.message, actor=p["sub"],
                         campaign_id=cid, expiry_days=body.expiry_days, propensity=_propensity(con, uid, body.product_id))
        sent.append(o["offer_id"])
    con.execute("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)", (cid, p["lender_id"], body.campaign_name or f"Campaign {cid}",
                                                                 body.product_id, now_iso(), len(body.user_ids), len(sent)))
    con.commit()
    return {"campaign_id": cid, "sent": len(sent), "skipped": skipped, "offer_ids": sent}


@router.post("/offers/{offer_id}/respond", summary="Applicant views, accepts or rejects an offer (score re-checked at acceptance)")
def respond_offer(offer_id: str, body: OfferResponseIn, p: dict = Depends(require_role("user"))):
    con = get_conn()
    uid = p["user_id"]
    current = None
    if body.action == "accept":
        invalidate(uid)
        prof = build_profile(con, uid, persist=True, trigger="offer_acceptance_recheck", actor=p["sub"])
        current = prof["policy"]["score"]
    try:
        o = respond(con, offer_id, uid, body.action, current)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        con.commit()
        raise HTTPException(409, str(e))
    return o


@router.get("/lenders/offers", tags=["lender portal"], summary="Offers sent by this lender, with status")
def lender_offers(p: dict = Depends(require_role("lender"))):
    con = get_conn()
    out = rows(con, """SELECT o.*, p.product_name, s.tier FROM offers o JOIN products p USING (product_id)
                       LEFT JOIN scores s ON s.user_id=o.user_id AND s.is_current=1
                       WHERE o.lender_id=? ORDER BY o.created_at DESC""", (p["lender_id"],))
    for o in out:
        o["contact"] = contact_for(con, o["user_id"], p["lender_id"], "lender")
    camps = rows(con, "SELECT * FROM campaigns WHERE lender_id=? ORDER BY created_at DESC", (p["lender_id"],))
    return {"offers": out, "campaigns": camps}
