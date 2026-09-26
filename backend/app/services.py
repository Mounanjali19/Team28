"""Orchestration: raw data -> features -> rules -> tier -> products -> explanation,
and, separately, features -> ML PD -> agreement, and -> propensity.

This is the only module that combines the primary (rule) and secondary (ML)
paths, and it does so after the rule result is final.
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict

import numpy as np

from app.config import log
from app.database.db import audit, now_iso, one, rows
from app.explainability.explain import policy_explanation, trace_lines
from app.features.engineering import compute_features
from app.features.userdata import UserData, add_months, d64
from app.ingestion.pipeline import load_user
from app.ml.agreement import agreement, confidence
from app.ml.features import pd_vector, propensity_vector
from app.ml.models import load_models
from app.recommendations.products import catalog, decision, eligibility, recommend
from app.rules import policy as P
from app.rules.engine import evaluate

_user_cache: "OrderedDict[str, UserData]" = OrderedDict()
_lock = threading.Lock()


def get_user_data(con, user_id: str) -> UserData | None:
    with _lock:
        if user_id in _user_cache:
            _user_cache.move_to_end(user_id)
            return _user_cache[user_id]
    ud = load_user(con, user_id)
    if ud is not None:
        with _lock:
            _user_cache[user_id] = ud
            if len(_user_cache) > 256:
                _user_cache.popitem(last=False)
    return ud


def invalidate(user_id: str):
    with _lock:
        _user_cache.pop(user_id, None)


def user_as_of(con, user_id: str) -> str:
    r = one(con, "SELECT as_of_date FROM users WHERE user_id=?", (user_id,))
    return r["as_of_date"] if r else P.LIVE_AS_OF.isoformat()


def rule_result(ud: UserData, as_of) -> tuple[dict, dict]:
    features = compute_features(ud, as_of)
    return features, evaluate(features)


# ---------------------------------------------------------------- ML (secondary)
def ml_validation(features: dict, rule: dict, cohort: str, models=None) -> dict:
    models = models or load_models()
    pdm = models.get("pd")
    if pdm is None:
        return {"available": False, "label": "ML Validation Signal", "text": "PD model not trained yet (run scripts/train_ml.py)."}
    pred = pdm.predict(pd_vector(features))
    in_support = cohort not in ("official_sample",)
    ok, reasons = confidence(features, in_support)
    band = P.ml_band_for(pred["pd"])
    agr = agreement(rule["tier"]["code"], band, ok)
    return {
        "available": True, "label": "ML Validation Signal", "model_version": pdm.version,
        "pd": round(pred["pd"], 4), "pd_pct": round(pred["pd"] * 100, 1),
        "ml_risk_score": int(round(1000 * (1 - pred["pd"]))),
        "ml_risk_score_label": "ML Risk Score = 1000 x (1 - PD). Validation signal only; not the credit score.",
        "band": band, "confident": ok, "confidence": "sufficient" if ok else "insufficient", "confidence_reasons": reasons,
        "agreement": agr, "risk_increasing_signals": pred["risk_increasing"], "risk_reducing_signals": pred["risk_reducing"],
        "text": (f"ML model estimates a {pred['pd'] * 100:.1f}% probability of default within 12 months ({band} band). "
                 + agr["text"]),
        "holdout_auc": pdm.metrics["test"]["auc"],
    }


def intent_counts(con, user_id: str, as_of: str, product_id: str | None = None) -> dict:
    start = str(add_months(d64(as_of), -3))
    ev = rows(con, """SELECT event_type, scenario_type, target_product_id, source FROM simulator_events
                      WHERE user_id=? AND ((event_ts >= ? AND event_ts < ?) OR source='app')""", (user_id, start, as_of))
    return {"simulate": sum(e["event_type"] == "simulate" for e in ev),
            "catalog_view": sum(e["event_type"] == "catalog_view" for e in ev),
            "target_match": sum(e["target_product_id"] == product_id for e in ev) if product_id else 0,
            "scenarios": len({e["scenario_type"] for e in ev if e["scenario_type"]})}


def propensities(con, user_id: str, as_of: str, features: dict, rule: dict, elig: list, models=None) -> dict:
    models = models or load_models()
    pm = models.get("propensity")
    if pm is None:
        return {}
    todo = [p for p in elig if p["eligible"]]            # PP-01: eligible products only
    vecs = []
    for p in todo:
        intent = intent_counts(con, user_id, as_of, p["product_id"])
        amount = ((p["amount_min"] or 0) + (p["amount_max"] or 0)) / 2 or None
        vecs.append(propensity_vector(rule["score"], p, features,
                                      {"rate": p["interest_rate_pct"], "amount": amount, "channel": "in_app", "campaign_type": "targeted"}, intent))
    return {p["product_id"]: round(x, 4) for p, x in zip(todo, pm.predict_many(vecs))}


# ---------------------------------------------------------------- full profile
def build_profile(con, user_id: str, persist: bool = False, trigger: str = "request", actor: str = "system",
                  ud: UserData | None = None, products: list | None = None) -> dict | None:
    t0 = time.perf_counter()
    u = one(con, "SELECT * FROM users WHERE user_id=?", (user_id,))
    if not u:
        return None
    ud = ud or get_user_data(con, user_id)
    features, rule = rule_result(ud, u["as_of_date"])
    products = products or catalog(con)
    elig = eligibility(rule["score"], products, rule["identity_blocked"])
    dec = decision(rule["score"], elig, rule["identity_blocked"])
    rule_ms = (time.perf_counter() - t0) * 1000
    # ----- secondary layer, after the rule result is final -----
    ml = ml_validation(features, rule, u["cohort"])
    props = propensities(con, user_id, u["as_of_date"], features, rule, elig)
    recs = recommend(elig, props, ml.get("confident", False))
    locked = sorted([p for p in elig if not p["eligible"] and not rule["identity_blocked"]], key=lambda p: p["min_score"])
    profile = {
        "user_id": user_id, "cohort": u["cohort"], "as_of": u["as_of_date"], "demo_label": u.get("demo_label"),
        "policy": {"label": "Rule-Based Policy Decision", **rule, "decision": dec, "trace": trace_lines(rule)},
        "explanation": policy_explanation(rule),
        "products": elig, "recommendations": recs, "next_locked_product": locked[0] if locked else None,
        "ml": ml, "propensity": props,
        "timing_ms": {"rule_engine": round(rule_ms, 1), "total": round((time.perf_counter() - t0) * 1000, 1)},
        "generated_at": now_iso(),
    }
    if persist:
        persist_score(con, user_id, profile, trigger, actor, commit=persist != "nocommit")
    return profile


def persist_score(con, user_id: str, profile: dict, trigger: str, actor: str = "system", commit: bool = True):
    pol = profile["policy"]
    con.execute("UPDATE scores SET is_current=0 WHERE user_id=? AND is_current=1", (user_id,))
    cur = con.execute("""INSERT INTO scores (user_id, as_of, score, raw_score, tier, decision, data_quality, rule_version, trigger,
                         computed_at, latency_ms, is_current, result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                      (user_id, pol["as_of"], pol["score"], pol["raw_score"], pol["tier"]["code"], pol["decision"]["code"],
                       pol["data_quality"]["status"], pol["rule_version"], trigger, now_iso(), profile["timing_ms"]["total"],
                       json.dumps({"policy": {k: v for k, v in pol.items() if k != "trace"}, "products": profile["products"]}, default=str)))
    sid = cur.lastrowid
    con.executemany("INSERT INTO score_factors VALUES (?,?,?,?,?,?,?)",
                    [(sid, r["id"], r["points"], r["max"], r["band"], r["value_display"], r["status"]) for r in pol["factors"]])
    ml = profile["ml"]
    if ml.get("available"):
        con.execute("UPDATE ml_predictions SET is_current=0 WHERE user_id=? AND is_current=1", (user_id,))
        con.execute("""INSERT INTO ml_predictions (user_id, score_id, model_version, pd, ml_risk_score, ml_band, confidence,
                       agreement_status, review_flag, detail_json, computed_at, is_current) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (user_id, sid, ml["model_version"], ml["pd"], ml["ml_risk_score"], ml["band"], ml["confidence"],
                     ml["agreement"]["status"], ml["agreement"]["review_flag"],
                     json.dumps({"risk_increasing": ml["risk_increasing_signals"], "risk_reducing": ml["risk_reducing_signals"],
                                 "propensity": profile["propensity"]}), now_iso()))
    audit(con, "score_calculated", actor, "user", user_id,
          {"score": pol["score"], "tier": pol["tier"]["code"], "decision": pol["decision"]["code"], "trigger": trigger,
           "review_flag": ml.get("agreement", {}).get("review_flag")},
          rule_version=pol["rule_version"], model_version=ml.get("model_version"))
    if commit:
        con.commit()
    return sid


def current_score_row(con, user_id: str) -> dict | None:
    return one(con, """SELECT s.*, m.pd, m.ml_band, m.agreement_status, m.review_flag, m.ml_risk_score, m.confidence
                       FROM scores s LEFT JOIN ml_predictions m ON m.user_id=s.user_id AND m.is_current=1
                       WHERE s.user_id=? AND s.is_current=1""", (user_id,))
