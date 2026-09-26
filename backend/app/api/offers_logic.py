"""Offer lifecycle rules (LP-04..LP-09), independent of HTTP."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.database.db import audit, now_iso, one, rows
from app.rules import policy as P


def _event(con, offer_id, event, actor, detail=None):
    con.execute("INSERT INTO offer_events (offer_id, event, actor, ts, detail_json) VALUES (?,?,?,?,?)",
                (offer_id, event, actor, now_iso(), json.dumps(detail or {})))


def check_push(con, lender_id: str, user_id: str, product_id: str) -> tuple[bool, str, dict | None, dict | None]:
    product = one(con, "SELECT * FROM products WHERE product_id=?", (product_id,))
    if not product:
        return False, "unknown product", None, None
    if product["lender_id"] != lender_id:
        return False, "lenders may only push their own catalog products (LP-06)", product, None
    s = one(con, """SELECT s.score, s.tier, s.result_json, u.match_confidence FROM scores s JOIN users u USING (user_id)
                    WHERE s.user_id=? AND s.is_current=1""", (user_id,))
    if not s:
        return False, "applicant has no policy score", product, None
    if s["match_confidence"] < P.WEAK_ID_THRESHOLD:
        return False, "identity match below 0.8: offers withheld until confirmed (LP-08)", product, s
    if s["score"] < product["min_score"]:
        return False, f"policy score {s['score']} is below the product minimum {product['min_score']} (LP-05)", product, s
    dup = one(con, "SELECT offer_id FROM offers WHERE user_id=? AND product_id=? AND lender_id=? AND status IN ('sent','viewed')",
              (user_id, product_id, lender_id))
    if dup:
        return False, "an open offer for this product already exists", product, s
    return True, "ok", product, s


def create_offer(con, lender_id, user_id, product_id, rate=None, amount=None, message=None, actor="lender",
                 campaign_id=None, expiry_days=None, propensity=None) -> dict:
    ok, reason, product, s = check_push(con, lender_id, user_id, product_id)
    if not ok:
        raise ValueError(reason)
    rate = rate if rate is not None else product["interest_rate_pct"]
    if amount is None:
        amount = product["amount_min"]
    if product["amount_min"] is not None and product["amount_max"] is not None and not (product["amount_min"] <= amount <= product["amount_max"]):
        raise ValueError(f"amount must be within the catalog range {product['amount_min']:.0f}-{product['amount_max']:.0f} (PE-07)")
    offer_id = "OFF_" + uuid.uuid4().hex[:10].upper()
    created = datetime.now(timezone.utc)
    expires = created + timedelta(days=expiry_days or P.OFFER_DEFAULT_EXPIRY_DAYS)
    con.execute("""INSERT INTO offers (offer_id, user_id, lender_id, product_id, interest_rate, amount, message, status, campaign_id,
                   score_at_offer, propensity, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (offer_id, user_id, lender_id, product_id, rate, amount, message, "sent", campaign_id, s["score"], propensity,
                 created.replace(microsecond=0).isoformat(), expires.replace(microsecond=0).isoformat()))
    _event(con, offer_id, "sent", actor, {"score_at_offer": s["score"], "min_score": product["min_score"]})
    audit(con, "offer_sent", actor, "offer", offer_id, {"user_id": user_id, "product_id": product_id, "lender_id": lender_id,
                                                         "score": s["score"]}, rule_version=P.RULE_VERSION)
    return one(con, "SELECT * FROM offers WHERE offer_id=?", (offer_id,))


def respond(con, offer_id: str, user_id: str, action: str, current_score: int | None) -> dict:
    o = one(con, "SELECT o.*, p.min_score FROM offers o JOIN products p USING (product_id) WHERE offer_id=? AND user_id=?", (offer_id, user_id))
    if not o:
        raise LookupError("offer not found")
    if o["status"] not in ("sent", "viewed"):
        raise ValueError(f"offer is already {o['status']}")
    if o["expires_at"] and o["expires_at"] < now_iso():
        con.execute("UPDATE offers SET status='expired' WHERE offer_id=?", (offer_id,))
        _event(con, offer_id, "expired", "system")
        raise ValueError("offer has expired")
    if action == "accept":
        if current_score is not None and current_score < o["min_score"]:          # LP-09 re-check at acceptance
            con.execute("UPDATE offers SET status='withdrawn', responded_at=? WHERE offer_id=?", (now_iso(), offer_id))
            _event(con, offer_id, "withdrawn", "system", {"reason": "score below product minimum at acceptance", "score": current_score})
            raise ValueError("your current policy score no longer meets this product's minimum; the offer was withdrawn")
        con.execute("UPDATE offers SET status='accepted', responded_at=? WHERE offer_id=?", (now_iso(), offer_id))
        con.execute("INSERT OR REPLACE INTO reveals VALUES (?,?,?,?)", (user_id, o["lender_id"], offer_id, now_iso()))
        _event(con, offer_id, "accepted", user_id, {"contact_revealed_to": o["lender_id"]})
    elif action == "reject":
        con.execute("UPDATE offers SET status='rejected', responded_at=? WHERE offer_id=?", (now_iso(), offer_id))
        _event(con, offer_id, "rejected", user_id)
    elif action == "view":
        if o["status"] == "sent":
            con.execute("UPDATE offers SET status='viewed' WHERE offer_id=?", (offer_id,))
            _event(con, offer_id, "viewed", user_id)
    else:
        raise ValueError("action must be accept, reject or view")
    audit(con, f"offer_{action}", user_id, "offer", offer_id, {"lender_id": o["lender_id"], "product_id": o["product_id"]})
    con.commit()
    return one(con, "SELECT * FROM offers WHERE offer_id=?", (offer_id,))


def is_revealed(con, user_id: str, lender_id: str | None) -> bool:
    if not lender_id:
        return False
    return one(con, "SELECT 1 AS x FROM reveals WHERE user_id=? AND lender_id=?", (user_id, lender_id)) is not None


def mask_name(name: str) -> str:
    return " ".join(w[0] + "*" * max(len(w) - 1, 3) for w in (name or "Applicant").split())


def mask_phone(phone: str) -> str:
    digits = [c for c in phone or "" if c.isalnum()]
    tail = "".join(digits[-4:])
    return "+91 ******" + tail


def contact_for(con, user_id: str, lender_id: str | None, role: str) -> dict:
    c = one(con, "SELECT * FROM contacts WHERE user_id=?", (user_id,)) or {"display_name": "Applicant", "phone": "", "locality": ""}
    if role == "user" or role == "admin" or is_revealed(con, user_id, lender_id):
        return {"display_name": c["display_name"], "phone": c["phone"], "locality": c["locality"], "masked": False}
    return {"display_name": mask_name(c["display_name"]), "phone": mask_phone(c["phone"]), "locality": "****** (hidden until offer accepted)",
            "masked": True}
