"""Rule-vs-ML agreement engine (rulebook Part 16, ML-04..ML-10).

The rule outcome is fixed before this runs. Disagreement never changes the
policy score, tier or eligibility; it only attaches a review flag.
"""
from __future__ import annotations

from app.rules import policy as P

STATUS_TEXT = {
    "STRONG_AGREEMENT": "ML supports the rule decision: the policy score is favourable and the model sees low default risk.",
    "AGREEMENT": "ML is broadly consistent with the rule decision.",
    "RULE_ELIGIBLE_ML_ELEVATED": "ML identifies elevated risk despite policy eligibility. The rule decision stands; enhanced review is recommended before disbursal.",
    "RULE_RISKY_ML_LOWER_RISK": "ML sees lower risk than the policy tier suggests. The rule decision stands; a lender may take a second look (inclusion case).",
    "STRONG_HIGH_RISK_AGREEMENT": "ML agrees the applicant is higher risk.",
    "INSUFFICIENT_ML_CONFIDENCE": "Not enough reliable data for the ML model to validate this decision; no agreement claim is made.",
}
REVIEW_FLAG = {
    "STRONG_AGREEMENT": "NONE", "AGREEMENT": "NONE", "STRONG_HIGH_RISK_AGREEMENT": "NONE",
    "RULE_ELIGIBLE_ML_ELEVATED": "ENHANCED_REVIEW", "RULE_RISKY_ML_LOWER_RISK": "SECOND_LOOK",
    "INSUFFICIENT_ML_CONFIDENCE": "ML_LOW_CONFIDENCE",
}
SHORT = {
    "STRONG_AGREEMENT": "Supports rule decision", "AGREEMENT": "Consistent with rule decision",
    "RULE_ELIGIBLE_ML_ELEVATED": "Elevated risk: enhanced review", "RULE_RISKY_ML_LOWER_RISK": "Lower risk: second look",
    "STRONG_HIGH_RISK_AGREEMENT": "Agrees: higher risk", "INSUFFICIENT_ML_CONFIDENCE": "Insufficient ML confidence",
}


def agreement(tier_code: str, ml_band: str, confident: bool) -> dict:
    if not confident:
        status = "INSUFFICIENT_ML_CONFIDENCE"
    elif tier_code in P.POLICY_ELIGIBLE_TIERS:
        status = "STRONG_AGREEMENT" if ml_band in ("Low", "Moderate") else "RULE_ELIGIBLE_ML_ELEVATED"
    elif ml_band == "Low" or (tier_code == "T1" and ml_band == "Moderate"):
        status = "RULE_RISKY_ML_LOWER_RISK"
    elif ml_band in ("Elevated", "High"):
        status = "STRONG_HIGH_RISK_AGREEMENT"
    else:
        status = "AGREEMENT"
    return {"status": status, "label": SHORT[status], "text": STATUS_TEXT[status], "review_flag": REVIEW_FLAG[status],
            "rule_changed": False}


def confidence(features: dict, in_support: bool = True) -> tuple[bool, list[str]]:
    """ML-06 confidence gate."""
    reasons = []
    codes = {f["code"] for f in features["flags"]}
    bad = sorted(codes & P.ML_LOW_CONFIDENCE_FLAGS)
    if bad:
        reasons.append("data flags: " + ", ".join(bad))
    if features["ml_values"].get("txn_months", 0) < P.ML_MIN_TXN_MONTHS:
        reasons.append(f"fewer than {P.ML_MIN_TXN_MONTHS} months of transactions")
    if not in_support:
        reasons.append("applicant profile is outside the model's training data (no employment/housing records)")
    return (not reasons), reasons
