"""Applicant endpoints: score, factors, products, history, data summary, ML validation, export."""
from __future__ import annotations

import json

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.offers_logic import contact_for
from app.database.db import get_conn, one, rows
from app.features.userdata import add_months, d64
from app.security.auth import assert_user_access, current_principal
from app.services import build_profile, get_user_data, invalidate

router = APIRouter(prefix="/api", tags=["applicants"])


def _profile(user_id: str, p: dict, persist=False, trigger="request"):
    assert_user_access(p, user_id)
    con = get_conn()
    prof = build_profile(con, user_id, persist=persist, trigger=trigger, actor=p["sub"])
    if prof is None:
        raise HTTPException(404, "applicant not found")
    prof["contact"] = contact_for(con, user_id, p.get("lender_id"), p["role"])
    if p["role"] == "user":        # applicants see review status, not the lender-facing PD detail (rulebook Part 16)
        prof["ml"] = {k: v for k, v in prof["ml"].items()}
    return prof


@router.get("/users/{user_id}", summary="Applicant overview (PII masked for lenders until an offer is accepted)")
def get_user(user_id: str, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    con = get_conn()
    u = one(con, "SELECT user_id, age, education_level, employment_status, monthly_income, city_tier, housing_status, cohort, as_of_date, "
                 "match_confidence, demo_label, source FROM users WHERE user_id=?", (user_id,))
    if not u:
        raise HTTPException(404, "applicant not found")
    u["contact"] = contact_for(con, user_id, p.get("lender_id"), p["role"])
    return u


@router.get("/users/{user_id}/score", summary="Full credit profile: policy score, tier, factors, products, explanation, ML validation")
def get_score(user_id: str, p: dict = Depends(current_principal)):
    return _profile(user_id, p)


@router.post("/users/{user_id}/score", summary="Recompute the score from raw data now and store it (score history is kept)")
def refresh_score(user_id: str, p: dict = Depends(current_principal)):
    invalidate(user_id)
    return _profile(user_id, p, persist=True, trigger="refresh")


@router.get("/users/{user_id}/factors", summary="Rule-by-rule score trace")
def factors(user_id: str, p: dict = Depends(current_principal)):
    prof = _profile(user_id, p)
    pol = prof["policy"]
    return {"score": pol["score"], "raw_score": pol["raw_score"], "capped": pol["capped"], "tier": pol["tier"],
            "components": pol["components"], "factors": pol["factors"], "trace": pol["trace"], "explanation": prof["explanation"],
            "data_quality": pol["data_quality"], "rule_version": pol["rule_version"]}


@router.get("/users/{user_id}/products", summary="Eligibility for every catalog product and ordered recommendations")
def products(user_id: str, p: dict = Depends(current_principal)):
    prof = _profile(user_id, p)
    return {"score": prof["policy"]["score"], "products": prof["products"], "recommendations": prof["recommendations"],
            "next_locked_product": prof["next_locked_product"], "propensity": prof["propensity"]}


@router.get("/users/{user_id}/history", summary="Stored score history (append-only)")
def history(user_id: str, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    return rows(get_conn(), """SELECT score_id, as_of, score, raw_score, tier, decision, data_quality, rule_version, trigger, computed_at,
                               latency_ms FROM scores WHERE user_id=? ORDER BY score_id DESC LIMIT 50""", (user_id,))


@router.get("/ml/{user_id}", tags=["ml"], summary="Secondary ML validation signal (Case 1 PD) and rule-vs-ML agreement")
def ml(user_id: str, p: dict = Depends(current_principal)):
    prof = _profile(user_id, p)
    return {"policy_score": prof["policy"]["score"], "policy_tier": prof["policy"]["tier"], "ml": prof["ml"], "propensity": prof["propensity"]}


@router.get("/users/{user_id}/export", summary="Download the credit profile as JSON")
def export(user_id: str, p: dict = Depends(current_principal)):
    prof = _profile(user_id, p)
    return JSONResponse(json.loads(json.dumps(prof, default=str)),
                        headers={"Content-Disposition": f'attachment; filename="altcredit_profile_{user_id}.json"'})


@router.get("/users/{user_id}/data-summary", summary="Monthly cash flow and bill history used by the engine (for charts)")
def data_summary(user_id: str, p: dict = Depends(current_principal)):
    assert_user_access(p, user_id)
    con = get_conn()
    u = one(con, "SELECT as_of_date FROM users WHERE user_id=?", (user_id,))
    if not u:
        raise HTTPException(404, "applicant not found")
    ud = get_user_data(con, user_id)
    as_of = d64(u["as_of_date"])
    start = add_months(as_of, -12)
    t = ud.txn
    m = (t["date"] >= start) & (t["date"] < as_of)
    months = np.unique(t["date"][m].astype("datetime64[M]"))
    series = []
    for mo in months:
        sel = m & (t["date"].astype("datetime64[M]") == mo)
        inc = float(t["amount"][sel & t["is_credit"]].sum())
        out = float(t["amount"][sel & ~t["is_credit"]].sum())
        disc = float(t["amount"][sel & ~t["is_credit"] & np.isin(t["category"], ["Dining", "Shopping"])].sum())
        series.append({"month": str(mo), "income": round(inc), "spend": round(out), "discretionary": round(disc), "net": round(inc - out)})
    o = ud.obl
    om = (o["due"] >= start) & (o["due"] < as_of)
    lag = np.where(np.isnat(o["paid"][om]) | (o["paid"][om] >= as_of), 999,
                   (o["paid"][om] - o["due"][om]).astype("timedelta64[D]").astype(np.int64))
    bills = {}
    for typ, l in zip(o["type"][om], lag):
        b = bills.setdefault(str(typ), {"due": 0, "on_time": 0, "late": 0})
        b["due"] += 1
        b["on_time" if l <= 0 else "late"] += 1
    counts = {"transactions": int(len(t["date"])), "bills": int(len(o["due"])), "credit_accounts": len(ud.accounts),
              "statements": int(len(ud.stmt["date"])), "life_events": int(len(ud.life["date"]))}
    return {"as_of": u["as_of_date"], "monthly": series, "bills_last_12m": bills, "record_counts": counts}
