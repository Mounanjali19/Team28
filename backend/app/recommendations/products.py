"""Product eligibility (rule-gated) and recommendation ordering.

Eligibility is decided only by the policy score (PE-01: score >= min_score).
Propensity (Case 2) may re-order eligible products but can never add, remove
or unlock one (PP-05).
"""
from __future__ import annotations

from app.database.db import rows


def catalog(con) -> list[dict]:
    return rows(con, "SELECT p.*, l.lender_name FROM products p LEFT JOIN lenders l USING (lender_id) ORDER BY min_score, product_id")


def eligibility(score: int, products: list[dict], identity_blocked: bool = False) -> list[dict]:
    out = []
    for p in products:
        ok = score >= p["min_score"] and not identity_blocked
        out.append({
            "product_id": p["product_id"], "product_name": p["product_name"], "type": p["type"],
            "min_score": p["min_score"], "applicant_score": score, "eligible": ok,
            "gap": max(0, p["min_score"] - score), "interest_rate": p["interest_rate"],
            "interest_rate_pct": p["interest_rate_pct"], "amount_min": p["amount_min"], "amount_max": p["amount_max"],
            "tenure_months": p["tenure_months"], "annual_fee": p["annual_fee"], "segment": p["segment"],
            "lender_id": p["lender_id"], "lender_name": p.get("lender_name"), "official": bool(p.get("official", 1)),
            "reason": ("Identity match must be confirmed before any product is offered" if identity_blocked and score >= p["min_score"]
                       else (f"Eligible: your policy score {score} meets the minimum of {p['min_score']}" if ok
                             else f"Locked: needs {p['min_score']}, you are {p['min_score'] - score} points short")),
        })
    return out


def recommend(elig: list[dict], propensity: dict | None = None, ml_confident: bool = False) -> list[dict]:
    """Order eligible products (PE-04 / PP-05). Returns eligible products only, best first."""
    eligible = [dict(p) for p in elig if p["eligible"]]
    use_prop = bool(propensity) and ml_confident
    for p in eligible:
        p["propensity"] = propensity.get(p["product_id"]) if propensity else None
    if use_prop:
        eligible.sort(key=lambda p: (-(p["propensity"] or 0), p["interest_rate_pct"] or 99, p["product_id"]))
        basis = "ordered by predicted acceptance (Case 2 propensity) among rule-eligible products"
    else:
        eligible.sort(key=lambda p: (-p["min_score"], p["interest_rate_pct"] or 99, p["product_id"]))
        basis = "ordered by product tier (highest minimum score first), then lower interest rate"
    for i, p in enumerate(eligible):
        p["rank"] = i + 1
        why = [f"your policy score qualifies (minimum {p['min_score']})"]
        if p["interest_rate_pct"] is not None:
            why.append(f"{p['interest_rate']} interest")
        if use_prop and p["propensity"] is not None:
            why.append(f"{p['propensity'] * 100:.0f}% predicted likelihood you would take it up")
        p["why_recommended"] = "; ".join(why)
        p["ordering_basis"] = basis
    return eligible


def decision(score: int, elig: list[dict], identity_blocked: bool) -> dict:
    """PE-03 Accept/Reject (+ Refer for the identity data gate, MD-12)."""
    if identity_blocked:
        return {"code": "REFER", "label": "Referred for identity check",
                "text": "Your identity match could not be confirmed, so the application is referred to manual review before any product is offered."}
    if any(p["eligible"] for p in elig):
        n = sum(p["eligible"] for p in elig)
        return {"code": "ACCEPT", "label": "Accept", "text": f"Accepted: your policy score of {score} qualifies you for {n} product(s)."}
    lowest = min((p["min_score"] for p in elig), default=None)
    return {"code": "REJECT", "label": "Reject",
            "text": f"Not accepted yet: your policy score of {score} is below the lowest product minimum ({lowest})."}
