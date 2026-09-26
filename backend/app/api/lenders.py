"""Lender portal: dashboard, candidate search/filter, candidate detail, analytics."""
from __future__ import annotations

import json
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.offers_logic import contact_for
from app.api.users import _profile
from app.database.db import get_conn, one, rows
from app.rules import policy as P
from app.security.auth import require_role

router = APIRouter(prefix="/api/lenders", tags=["lender portal"])
POOL = ("live", "uploaded", "official_sample")


def _candidates_base(con, lender_id: str | None):
    return rows(con, f"""
        SELECT u.user_id, u.age, u.employment_status, u.monthly_income, u.city_tier, u.housing_status, u.cohort, u.match_confidence,
               s.score, s.raw_score, s.tier, s.decision, s.data_quality, s.computed_at,
               m.pd, m.ml_band, m.agreement_status, m.review_flag, m.confidence AS ml_confidence, m.detail_json,
               (SELECT o.status FROM offers o WHERE o.user_id=u.user_id AND o.lender_id=? ORDER BY o.created_at DESC LIMIT 1) AS offer_status
        FROM users u JOIN scores s ON s.user_id=u.user_id AND s.is_current=1
        LEFT JOIN ml_predictions m ON m.user_id=u.user_id AND m.is_current=1
        WHERE u.cohort IN ({','.join('?' * len(POOL))})""", (lender_id, *POOL))


@router.get("/me")
def me(p: dict = Depends(require_role("lender"))):
    con = get_conn()
    lender = one(con, "SELECT * FROM lenders WHERE lender_id=?", (p["lender_id"],))
    lender["products"] = rows(con, "SELECT * FROM products WHERE lender_id=? ORDER BY min_score", (p["lender_id"],))
    return lender


@router.get("/candidates", summary="Search and filter scored applicants (PII masked; default score range 650-1000)")
def candidates(
    p: dict = Depends(require_role("lender", "admin")),
    score_min: int = Query(P.LENDER_DEFAULT_MIN_SCORE, ge=0, le=1000), score_max: int = Query(P.LENDER_DEFAULT_MAX_SCORE, ge=0, le=1000),
    tiers: list[str] | None = Query(None), eligible_for: str | None = None, validation: list[str] | None = Query(None),
    review_flag: str | None = None, pd_min: float | None = Query(None, ge=0, le=1), pd_max: float | None = Query(None, ge=0, le=1),
    employment: list[str] | None = Query(None), income_min: float | None = None, income_max: float | None = None,
    city_tier: list[int] | None = Query(None), data_quality: list[str] | None = Query(None), exclude_offered: bool = False,
    sort: Literal["score", "pd", "propensity", "income"] = "score", order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
):
    con = get_conn()
    products = rows(con, "SELECT product_id, product_name, min_score, lender_id FROM products ORDER BY min_score")
    min_of = {x["product_id"]: x["min_score"] for x in products}
    own = [x["product_id"] for x in products if x["lender_id"] == p.get("lender_id")]
    out = []
    for c in _candidates_base(con, p.get("lender_id")):
        if not (score_min <= c["score"] <= score_max):
            continue
        if tiers and c["tier"] not in tiers:
            continue
        if eligible_for and (eligible_for not in min_of or c["score"] < min_of[eligible_for]):
            continue
        if validation and c["agreement_status"] not in validation:
            continue
        if review_flag and c["review_flag"] != review_flag:
            continue
        if pd_min is not None and (c["pd"] is None or c["pd"] < pd_min):
            continue
        if pd_max is not None and (c["pd"] is None or c["pd"] > pd_max):
            continue
        if employment and c["employment_status"] not in employment:
            continue
        if income_min is not None and (c["monthly_income"] or 0) < income_min:
            continue
        if income_max is not None and (c["monthly_income"] or 0) > income_max:
            continue
        if city_tier and c["city_tier"] not in city_tier:
            continue
        if data_quality and c["data_quality"] not in data_quality:
            continue
        if exclude_offered and c["offer_status"]:
            continue
        prop = json.loads(c.pop("detail_json") or "{}").get("propensity", {})
        c["eligible_products"] = [pid for pid, ms in min_of.items() if c["score"] >= ms] if c["match_confidence"] >= P.NO_SCORE_ID_THRESHOLD else []
        c["propensity_own_products"] = {k: v for k, v in prop.items() if k in own}
        c["best_propensity"] = max(c["propensity_own_products"].values(), default=None)
        c["weak_id"] = c["match_confidence"] < P.WEAK_ID_THRESHOLD
        c["contact"] = contact_for(con, c["user_id"], p.get("lender_id"), p["role"])
        c["monthly_income"] = None if c["monthly_income"] is None else round(c["monthly_income"])
        out.append(c)
    key = {"score": lambda c: (c["score"], c["raw_score"]), "pd": lambda c: c["pd"] if c["pd"] is not None else 9,
           "propensity": lambda c: c["best_propensity"] or 0, "income": lambda c: c["monthly_income"] or 0}[sort]
    out.sort(key=lambda c: c["user_id"])
    out.sort(key=key, reverse=(order == "desc"))
    total = len(out)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size, "items": out[start:start + page_size],
            "filters_applied": {"score_range": [score_min, score_max], "sort": sort, "note": "Default sort is policy score (LP-07); ML PD is a validation column."}}


@router.get("/candidates/{user_id}", summary="Candidate risk profile: rule breakdown, ML validation, behaviour, offers")
def candidate(user_id: str, p: dict = Depends(require_role("lender", "admin"))):
    con = get_conn()
    u = one(con, "SELECT cohort FROM users WHERE user_id=?", (user_id,))
    if not u or u["cohort"] not in POOL:
        raise HTTPException(404, "candidate not found")
    prof = _profile(user_id, p)
    prof["offers_from_you"] = rows(con, "SELECT * FROM offers WHERE user_id=? AND lender_id=? ORDER BY created_at DESC", (user_id, p.get("lender_id")))
    prof["own_products"] = [x for x in prof["products"] if x["lender_id"] == p.get("lender_id")]
    return prof


@router.get("/dashboard", summary="KPIs for the lender home page")
def dashboard(p: dict = Depends(require_role("lender", "admin"))):
    con = get_conn()
    base = _candidates_base(con, p.get("lender_id"))
    own = rows(con, "SELECT product_id, product_name, min_score FROM products WHERE lender_id=?", (p.get("lender_id"),))
    lowest_own = min((x["min_score"] for x in own), default=P.LENDER_DEFAULT_MIN_SCORE)
    offers = rows(con, "SELECT status, COUNT(*) AS n FROM offers WHERE lender_id=? GROUP BY status", (p.get("lender_id"),))
    by = {o["status"]: o["n"] for o in offers}
    responded = by.get("accepted", 0) + by.get("rejected", 0)
    tiers = {}
    for c in base:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    return {
        "candidates": len(base),
        "eligible_for_your_products": sum(1 for c in base if c["score"] >= lowest_own and c["match_confidence"] >= P.WEAK_ID_THRESHOLD),
        "above_default_filter": sum(1 for c in base if c["score"] >= P.LENDER_DEFAULT_MIN_SCORE),
        "pending_offers": by.get("sent", 0) + by.get("viewed", 0), "offers_by_status": by,
        "acceptance_rate": round(by.get("accepted", 0) / responded, 3) if responded else None,
        "enhanced_review": sum(1 for c in base if c["review_flag"] == "ENHANCED_REVIEW"),
        "second_look": sum(1 for c in base if c["review_flag"] == "SECOND_LOOK"),
        "tier_counts": tiers, "your_products": own,
    }


def _hist(values, edges):
    counts, _ = np.histogram(values, bins=edges)
    return [{"from": int(edges[i]) if float(edges[i]).is_integer() else round(float(edges[i]), 3),
             "to": int(edges[i + 1]) if float(edges[i + 1]).is_integer() else round(float(edges[i + 1]), 3), "count": int(c)}
            for i, c in enumerate(counts)]


@router.get("/analytics", summary="Portfolio analytics for the demo population")
def analytics(p: dict = Depends(require_role("lender", "admin")), population: Literal["live", "historical", "all_pool"] = "live"):
    con = get_conn()
    cohorts = {"live": ("live",), "historical": ("historical",), "all_pool": POOL}[population]
    data = rows(con, f"""SELECT s.score, s.tier, s.data_quality, m.pd, m.agreement_status, m.review_flag, m.detail_json
                         FROM users u JOIN scores s ON s.user_id=u.user_id AND s.is_current=1
                         LEFT JOIN ml_predictions m ON m.user_id=u.user_id AND m.is_current=1
                         WHERE u.cohort IN ({','.join('?' * len(cohorts))})""", cohorts)
    products = rows(con, "SELECT product_id, product_name, min_score FROM products ORDER BY min_score")
    scores = [d["score"] for d in data]
    pds = [d["pd"] for d in data if d["pd"] is not None]
    agree = {}
    for d in data:
        agree[d["agreement_status"] or "NONE"] = agree.get(d["agreement_status"] or "NONE", 0) + 1
    confident = [d for d in data if d["agreement_status"] and d["agreement_status"] != "INSUFFICIENT_ML_CONFIDENCE"]
    agreeing = [d for d in confident if d["agreement_status"] in ("STRONG_AGREEMENT", "AGREEMENT", "STRONG_HIGH_RISK_AGREEMENT")]
    props = {}
    for d in data:
        for k, v in json.loads(d["detail_json"] or "{}").get("propensity", {}).items():
            props.setdefault(k, []).append(v)
    tier_counts = {t.code: 0 for t in P.RISK_TIERS}
    for d in data:
        tier_counts[d["tier"]] += 1
    hist_offers = rows(con, "SELECT product_id, COUNT(*) AS n, SUM(response='accepted') AS acc FROM historical_offers GROUP BY product_id")
    app_offers = rows(con, "SELECT status, COUNT(*) AS n FROM offers GROUP BY status")
    sims = rows(con, "SELECT scenario_type, source, COUNT(*) AS n FROM simulator_events WHERE event_type='simulate' GROUP BY scenario_type, source ORDER BY n DESC")
    hist_default = rows(con, """SELECT s.tier, COUNT(*) AS n, AVG(h.default_12m) AS default_rate FROM historical_applications h
                                JOIN scores s ON s.user_id=h.user_id AND s.is_current=1 WHERE h.default_12m IS NOT NULL GROUP BY s.tier""")
    return {
        "population": population, "n": len(data),
        "score_distribution": _hist(scores, np.arange(0, 1001, 50)) if scores else [],
        "tier_distribution": [{"tier": t.code, "name": t.name, "color": t.color, "count": tier_counts[t.code]} for t in P.RISK_TIERS],
        "product_eligibility": [{"product_id": x["product_id"], "product_name": x["product_name"], "min_score": x["min_score"],
                                 "eligible": sum(s >= x["min_score"] for s in scores)} for x in products],
        "ml_pd_distribution": _hist(pds, np.array([0, .02, .05, .08, .12, .18, .25, .4, 1.0])) if pds else [],
        "agreement": agree,
        "agreement_rate": round(len(agreeing) / len(confident), 3) if confident else None,
        "propensity_mean": {k: round(float(np.mean(v)), 3) for k, v in props.items()},
        "offer_acceptance_historical": [{"product_id": h["product_id"], "offers": h["n"], "acceptance_rate": round(h["acc"] / h["n"], 3)} for h in hist_offers],
        "offers_in_app": {a["status"]: a["n"] for a in app_offers},
        "simulator_usage": sims[:12],
        "historical_default_rate_by_tier": sorted([{"tier": h["tier"], "n": h["n"], "default_rate": round(h["default_rate"], 3)} for h in hist_default],
                                                  key=lambda x: x["tier"]),
        "data_quality": {k: sum(d["data_quality"] == k for d in data) for k in ("GOOD", "LIMITED", "POOR")},
    }
