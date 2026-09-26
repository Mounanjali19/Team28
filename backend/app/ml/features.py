"""ML feature vectors (Case 1 PD and Case 2 propensity).

Built from the *measured values* of the feature pipeline, never from rule
points or the rule score (rule ML-08). Every value is computed as of the
decision date, from records strictly before it, so no future information and
no outcome can leak in. The propensity model is the one place where the policy
score is an input, because the use case lists it explicitly as a Case 2 input.
"""
from __future__ import annotations

import math

import numpy as np

EDU_ORDINAL = {"below_hs": 0, "high_school": 1, "diploma_cert": 2, "bachelor": 3, "master": 4, "phd": 5}
EMP_TYPES = ["salaried", "self_employed", "freelancer", "gig", "student", "unemployed"]
HOUSING = ["own", "rent", "family", "none"]

PD_FEATURES = [
    "tenure_months", "telecom_on_time_share", "education_ordinal", "spend_to_income", "essential_share",
    "cashflow_volatility", "days_saved", "on_time_rate", "debt_to_income", "has_credit_line", "utilization",
    "delinquency_events_24m", "worst_dpd_24m", "late_under_30_24m", "habit_count", "inquiries_6m", "address_changes_12m",
    "log_income", "income_cv", "lifestyle_share", "age", "city_tier", "late_bills_12m", "has_loan", "autopay_share",
    "income_missing", "rent_streak_months", "residence_months",
] + [f"emp_{e}" for e in EMP_TYPES] + [f"housing_{h}" for h in HOUSING]

FRIENDLY = {
    "tenure_months": "time in current job", "telecom_on_time_share": "mobile/internet bill regularity",
    "education_ordinal": "education level", "spend_to_income": "spend-to-income ratio", "essential_share": "share of essential spending",
    "cashflow_volatility": "cash-flow volatility", "days_saved": "savings buffer", "on_time_rate": "on-time bill payments",
    "debt_to_income": "debt-to-income ratio", "has_credit_line": "holding a credit line", "utilization": "credit utilization",
    "delinquency_events_24m": "30+ day late payments (24 months)", "worst_dpd_24m": "worst days past due",
    "late_under_30_24m": "short (under 30 day) late payments", "habit_count": "positive savings habits",
    "inquiries_6m": "recent credit inquiries", "address_changes_12m": "recent address changes", "log_income": "income level",
    "income_cv": "income volatility", "lifestyle_share": "lifestyle (dining/shopping) spending share", "age": "age",
    "city_tier": "city tier", "late_bills_12m": "late bills in the last 12 months", "has_loan": "existing loan",
    "autopay_share": "use of autopay", "income_missing": "income not verifiable", "rent_streak_months": "on-time rent streak",
    "residence_months": "time at current address",
} | {f"emp_{e}": f"employment type: {e}" for e in EMP_TYPES} | {f"housing_{h}": f"housing: {h}" for h in HOUSING}


def _num(v):
    if v is None:
        return np.nan
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if math.isfinite(x) else np.nan


def pd_vector(features: dict) -> dict:
    fx = features["factors"]
    mv = features["ml_values"]
    income = mv.get("income")
    util = fx["3.3"]["value"]
    v = {
        "tenure_months": fx["1.1"]["evidence"]["spell_months"] if fx["1.1"]["evidence"]["counted"] else 0,
        "telecom_on_time_share": _num(fx["1.3"]["value"]),
        "education_ordinal": EDU_ORDINAL.get(fx["1.4"]["value"], np.nan),
        "spend_to_income": min(_num(fx["2.1"]["value"]), 3.0) if fx["2.1"]["value"] is not None else np.nan,
        "essential_share": _num(fx["2.2"]["value"]),
        "cashflow_volatility": min(_num(fx["2.3"]["value"]), 3.0) if fx["2.3"]["value"] is not None else np.nan,
        "days_saved": min(_num(fx["2.4"]["value"]), 720) if fx["2.4"]["value"] is not None else np.nan,
        "on_time_rate": _num(fx["3.1"]["value"]),
        "debt_to_income": min(_num(fx["3.2"]["value"]), 3.0) if fx["3.2"]["value"] is not None else np.nan,
        "has_credit_line": 1.0 if fx["3.3"]["evidence"]["open_lines"] > 0 else 0.0,
        "utilization": min(_num(util), 2.0) if util is not None else 0.0,
        "delinquency_events_24m": min(fx["3.4"]["value"], 10),
        "worst_dpd_24m": min(fx["3.4"]["evidence"]["worst_dpd"], 365),
        "late_under_30_24m": min(fx["3.4"]["evidence"]["late_under_30"], 24),
        "habit_count": fx["4.1"]["value"],
        "inquiries_6m": fx["4.2"]["evidence"]["inquiries_6m"],
        "address_changes_12m": fx["4.2"]["evidence"]["address_changes_12m"],
        "log_income": math.log1p(income) if income else np.nan,
        "income_cv": min(_num(mv.get("income_cv")), 5.0) if mv.get("income_cv") is not None else np.nan,
        "lifestyle_share": _num(mv.get("lifestyle_share")),
        "age": _num(mv.get("age")),
        "city_tier": _num(mv.get("city_tier")),
        "late_bills_12m": mv.get("late_bills_12m", 0),
        "has_loan": 1.0 if mv.get("has_loan") else 0.0,
        "autopay_share": _num(fx["3.1"]["evidence"].get("autopay_share")),
        "income_missing": 1.0 if income is None else 0.0,
        "rent_streak_months": fx["1.2"]["evidence"]["rent_streak_months"],
        "residence_months": fx["1.2"]["evidence"]["residence_months"],
    }
    emp = mv.get("employment_type")
    for e in EMP_TYPES:
        v[f"emp_{e}"] = 1.0 if emp == e else 0.0
    h = mv.get("housing_status")
    for x in HOUSING:
        v[f"housing_{x}"] = 1.0 if h == x else 0.0
    return v


PROPENSITY_FEATURES = [
    "policy_score", "score_margin", "product_P_01", "product_P_02", "product_P_03", "product_P_04", "product_P_05",
    "is_card", "offered_rate", "log_offered_amount", "channel_in_app", "channel_push", "channel_sms", "campaign_targeted",
    "lifestyle_share", "spend_to_income", "log_income", "age", "has_credit_line", "sim_events_90d", "sim_target_match_90d",
    "catalog_views_90d", "sim_scenarios_90d",
]


def propensity_vector(policy_score: int, product: dict, features: dict, offer: dict, intent: dict) -> dict:
    mv = features["ml_values"]
    fx = features["factors"]
    income = mv.get("income")
    v = {
        "policy_score": policy_score,
        "score_margin": policy_score - product["min_score"],
        "is_card": 1.0 if "card" in str(product["type"]).lower() else 0.0,
        "offered_rate": _num(offer.get("rate")),
        "log_offered_amount": math.log1p(offer["amount"]) if offer.get("amount") else np.nan,
        "channel_in_app": 1.0 if offer.get("channel") == "in_app" else 0.0,
        "channel_push": 1.0 if offer.get("channel") == "push" else 0.0,
        "channel_sms": 1.0 if offer.get("channel") == "sms" else 0.0,
        "campaign_targeted": 1.0 if offer.get("campaign_type") == "targeted" else 0.0,
        "lifestyle_share": _num(mv.get("lifestyle_share")),
        "spend_to_income": min(_num(fx["2.1"]["value"]), 3.0) if fx["2.1"]["value"] is not None else np.nan,
        "log_income": math.log1p(income) if income else np.nan,
        "age": _num(mv.get("age")),
        "has_credit_line": 1.0 if fx["3.3"]["evidence"]["open_lines"] > 0 else 0.0,
        "sim_events_90d": intent.get("simulate", 0),
        "sim_target_match_90d": intent.get("target_match", 0),
        "catalog_views_90d": intent.get("catalog_view", 0),
        "sim_scenarios_90d": intent.get("scenarios", 0),
    }
    for p in ("P_01", "P_02", "P_03", "P_04", "P_05"):
        v[f"product_{p}"] = 1.0 if product["product_id"] == p else 0.0
    return v
