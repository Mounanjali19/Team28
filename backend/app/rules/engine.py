"""Deterministic rule-based credit engine (PRIMARY, authoritative).

``evaluate(features)`` turns the measured sub-factor values from
``app.features.engineering.compute_features`` into points using the official
scoring table in ``app.rules.policy``. Each rule returns one *reason record*
(rule EX-01); the score, the UI trace, the transparency PDF and the JSON
export are all rendered from these same records, so an explanation can never
contradict the score.

ML outputs are never read here (rule ML-07).
"""
from __future__ import annotations

from app.rules import policy as P


def _pct(x):
    return f"{x * 100:.1f}%"


def _money(x):
    return f"Rs {x:,.0f}"


def _rec(fid, points, band, value, display, status, text, evidence, note=None):
    mx = P.FACTOR_MAX[fid]
    return {
        "id": fid, "name": P.FACTOR_NAMES[fid], "component": P.FACTOR_COMPONENT[fid],
        "points": int(points), "max": mx, "min": P.FACTOR_MIN[fid], "band": band, "value": value,
        "value_display": display, "status": status, "text": text, "evidence": evidence, "note": note,
    }


# --------------------------------------------------------------------------- 1.x
def rule_1_1(f):
    v = f["value"]
    ev = f["evidence"]
    pts, band = P.BANDS["1.1"].evaluate(v)
    if f["status"] == "missing":
        text = "0 pts: no current employment record was found"
    elif ev["employment_type"] and not ev["counted"]:
        text = f"0 pts: current status is {ev['employment_type']}, which is not a job for this factor"
    else:
        kind = "continuous gig/freelance income" if ev["employment_type"] in P.GIG_TYPES else "your current job"
        text = f"{pts:+d} pts: {v} months of {kind} ({band})"
    return _rec("1.1", pts, band, v, f"{v} months", f["status"], text, ev)


def rule_1_2(f):
    state = f["value"]
    ev = f["evidence"]
    pts = 0 if state == "missing" else P.HOUSING_POINTS[state]
    labels = {
        "own": "owns home", "rent_12m_on_time": "renting, 12+ months of on-time rent",
        "rent_short": "renting, on-time rent history under 12 months", "family": "lives with family",
        "rent_12m_broken_streak": "renting 12+ months, but a rent payment in the last 12 was late",
        "none": "no stable address", "missing": "housing status unavailable",
    }
    band = labels[state]
    note = None
    if state == "family":
        note = "Family housing is not in the official table; scored 30 (project decision)."
    if state == "rent_12m_broken_streak":
        note = "Renter 12+ months with a late rent bill is not in the official table; scored 30 (open decision D3)."
    text = f"{pts:+d} pts: {band}"
    if state.startswith("rent") and ev["rent_bills_last12"]:
        text += f" ({ev['rent_bills_last12'] - ev['rent_late_last12']} of the last {ev['rent_bills_last12']} rent payments on time)"
    return _rec("1.2", pts, band, state, band, f["status"], text, ev, note)


def rule_1_3(f):
    v, ev = f["value"], f["evidence"]
    if v is None:
        return _rec("1.3", 0, "insufficient history", None, "n/a", f["status"],
                    f"0 pts: only {ev['months_with_bill']} months of mobile/internet bills (6 needed)", ev)
    pts, band = P.BANDS["1.3"].evaluate(v)
    text = f"{pts:+d} pts: mobile/internet bills paid on time in {ev['on_time_months']} of {ev['months_with_bill']} months ({_pct(v)})"
    return _rec("1.3", pts, band, v, _pct(v), f["status"], text, ev)


def rule_1_4(f):
    v = f["value"]
    if v is None:
        return _rec("1.4", 0, "not provided", None, "n/a", "missing", "0 pts: education not provided", f["evidence"])
    pts = P.EDUCATION_POINTS[v]
    nice = {"phd": "PhD", "master": "Master's degree", "bachelor": "Bachelor's degree", "diploma_cert": "Professional certification / diploma",
            "high_school": "High school", "below_hs": "Below high school"}[v]
    return _rec("1.4", pts, nice, v, nice, "ok", f"{pts:+d} pts: {nice}", f["evidence"])


# --------------------------------------------------------------------------- 2.x
def _missing_text(fid, f, what):
    if f["status"] == "missing":
        return _rec(fid, 0, "income missing", None, "n/a", "missing", f"0 pts: {what} cannot be measured without income", f["evidence"])
    return _rec(fid, 0, "insufficient history", None, "n/a", "insufficient", f"0 pts: fewer than 3 months of transactions to measure {what}", f["evidence"])


def rule_2_1(f):
    v = f["value"]
    if v is None:
        return _missing_text("2.1", f, "spend-to-income")
    pts, band = P.BANDS["2.1"].evaluate(v)
    ev = f["evidence"]
    text = f"{pts:+d} pts: you spend {_pct(v)} of your income ({_money(ev['avg_monthly_spend'])} of {_money(ev['monthly_income'])} a month)"
    return _rec("2.1", pts, band, v, _pct(v), f["status"], text, ev)


def rule_2_2(f):
    v = f["value"]
    if v is None:
        return _missing_text("2.2", f, "expense mix")
    pts, band = P.BANDS["2.2"].evaluate(v)
    return _rec("2.2", pts, band, v, _pct(v), f["status"], f"{pts:+d} pts: {_pct(v)} of your spending goes on essentials", f["evidence"])


def rule_2_3(f):
    v = f["value"]
    if v is None:
        return _missing_text("2.3", f, "cash-flow volatility")
    pts, band = P.BANDS["2.3"].evaluate(v)
    return _rec("2.3", pts, band, v, _pct(v), f["status"],
                f"{pts:+d} pts: your monthly net cash flow varies by {_pct(v)} of income (std-dev over 6 months)", f["evidence"])


def rule_2_4(f):
    v = f["value"]
    if v is None:
        return _missing_text("2.4", f, "savings buffer")
    pts, band = P.BANDS["2.4"].evaluate(v)
    return _rec("2.4", pts, band, v, f"{v} days", f["status"],
                f"{pts:+d} pts: your liquid balance covers {v} days of income", f["evidence"])


# --------------------------------------------------------------------------- 3.x
def rule_3_1(f):
    v, ev = f["value"], f["evidence"]
    if v is None:
        return _rec("3.1", 0, "insufficient history", None, "n/a", f["status"],
                    f"0 pts: only {ev['bills_due']} bills due in the last 12 months (6 needed)", ev)
    pts, band = P.BANDS["3.1"].evaluate(v)
    text = f"{pts:+d} pts: {ev['bills_on_time']} of {ev['bills_due']} bills paid on or before the due date in the last 12 months ({_pct(v)})"
    return _rec("3.1", pts, band, v, _pct(v), f["status"], text, ev)


def rule_3_2(f):
    v = f["value"]
    if v is None:
        return _missing_text("3.2", f, "debt-to-income")
    pts, band = P.BANDS["3.2"].evaluate(v)
    ev = f["evidence"]
    text = (f"{pts:+d} pts: debt payments take {_pct(v)} of your income" if ev["monthly_debt_due"] > 0
            else f"{pts:+d} pts: no recurring debt payments (0% of income)")
    return _rec("3.2", pts, band, v, _pct(v), f["status"], text, ev)


def rule_3_3(f):
    v, ev = f["value"], f["evidence"]
    if f["status"] == "na":
        return _rec("3.3", P.NO_CREDIT_LINE_POINTS, "no credit line (not applicable, neutral)", None, "no line", "na",
                    f"+{P.NO_CREDIT_LINE_POINTS} pts: you have no credit line, so utilization does not apply (neutral score)", ev,
                    "No-credit-line handling is a project decision; absence of credit is not penalised beyond the neutral band.")
    if f["status"] == "unverified":
        return _rec("3.3", P.UNVERIFIED_LINE_POINTS, "line not yet verified (provisional)", None, "unverified", "unverified",
                    f"+{P.UNVERIFIED_LINE_POINTS} pts: credit line has no statement yet, utilization provisionally neutral", ev)
    pts, band = P.BANDS["3.3"].evaluate(v)
    return _rec("3.3", pts, band, v, _pct(v), "ok",
                f"{pts:+d} pts: using {_pct(v)} of your credit limit ({_money(ev['total_outstanding'])} of {_money(ev['total_limit'])})", ev)


def rule_3_4(f):
    n, ev = f["value"], f["evidence"]
    worst = ev["worst_dpd"]
    if n == 0:
        key, band = "none", "no payment 30+ days late in 24 months"
    elif n == 1 and worst < 60:
        key, band = "one_30", "one payment 30-59 days late"
    elif n == 1 and worst < 90:
        key, band = "one_60", "one payment 60-89 days late"
    else:
        key, band = "one_90_or_multiple", (f"{n} payments 30+ days late" if n > 1 else "one payment 90+ days late")
    pts = P.DELINQUENCY_POINTS[key]
    text = f"{pts:+d} pts: {band} in the last 24 months"
    if n >= 1 and ev["event_list"]:
        last = ev["event_list"][-1]
        text += f" (latest: {last['type']}, due {last['due_date']}, {last['dpd']} days late)"
    return _rec("3.4", pts, band, n, f"{n} events", f["status"], text, ev)


# --------------------------------------------------------------------------- 4.x
def rule_4_1(f):
    n, ev = f["value"], f["evidence"]
    pts = min(n * P.HABIT_POINTS_EACH, P.HABIT_CAP)
    if n == 0:
        text = "0 pts: no qualifying positive habit in the last 12 months"
    else:
        text = f"{pts:+d} pts: " + "; ".join(f"{h['name']} ({h['evidence']})" for h in ev["habits"])
    return _rec("4.1", pts, f"{n} habit(s)", n, f"{n} habits", "ok", text, ev)


def rule_4_2(f):
    n, ev = f["value"], f["evidence"]
    pts = max(n * P.FLAG_POINTS_EACH, P.FLAG_CAP)
    if n == 0:
        text = "0 pts: no active risk flags"
    else:
        text = f"{pts:+d} pts: " + "; ".join(f"{r['name']} ({r['evidence']}, expires {r['expires']})" for r in ev["flags"])
    return _rec("4.2", pts, f"{n} flag(s)", n, f"{n} flags", "ok", text, ev)


RULES = [
    ("1.1", rule_1_1), ("1.2", rule_1_2), ("1.3", rule_1_3), ("1.4", rule_1_4),
    ("2.1", rule_2_1), ("2.2", rule_2_2), ("2.3", rule_2_3), ("2.4", rule_2_4),
    ("3.1", rule_3_1), ("3.2", rule_3_2), ("3.3", rule_3_3), ("3.4", rule_3_4),
    ("4.1", rule_4_1), ("4.2", rule_4_2),
]

RULE_CATALOG = [
    {"rule_id": "R-1.1", "factor": "1.1", "name": "Employment Stability", "input": "employment_tenure_months", "thresholds": ">=24:150, 12-23:100, 6-11:50, else 0", "class": "OFFICIAL", "edge_cases": "student/unemployed/no spell -> 0; gig -> continuous income months"},
    {"rule_id": "R-1.2", "factor": "1.2", "name": "Housing Status", "input": "housing_state", "thresholds": "own 80; rent+12mo on-time 60; rent<12mo 30; family 30; none 0", "class": "OFFICIAL", "edge_cases": "family=30 project decision; renter 12mo with late rent=30 (D3)"},
    {"rule_id": "R-1.3", "factor": "1.3", "name": "Digital Footprint", "input": "telecom_on_time_month_share", "thresholds": ">=95%:70, 80-94%:45, 60-79%:20, else 0", "class": "OFFICIAL", "edge_cases": "<6 months of telecom bills -> 0 + flag"},
    {"rule_id": "R-1.4", "factor": "1.4", "name": "Education / Skill Level", "input": "education_level", "thresholds": "master/phd 50, bachelor 40, cert 30, high school 20, below 0", "class": "OFFICIAL", "edge_cases": "missing -> 0 + flag"},
    {"rule_id": "R-2.1", "factor": "2.1", "name": "Spend-to-Income Ratio", "input": "spend_to_income", "thresholds": "<=30%:120, 30-50%:80, 50-70%:40, else 0", "class": "OFFICIAL", "edge_cases": "income missing -> 0; <3 months -> 0"},
    {"rule_id": "R-2.2", "factor": "2.2", "name": "Expense Diversity", "input": "essential_share", "thresholds": ">=70%:80, 55-69%:45, 40-54%:20, else 0", "class": "OFFICIAL", "edge_cases": "no classified spend -> 0"},
    {"rule_id": "R-2.3", "factor": "2.3", "name": "Cash-flow Volatility", "input": "cashflow_volatility", "thresholds": "<=5%:70, 5-10%:40, 10-20%:15, else 0", "class": "OFFICIAL", "edge_cases": "<3 months -> 0"},
    {"rule_id": "R-2.4", "factor": "2.4", "name": "Savings / Emergency Fund", "input": "days_of_income_saved", "thresholds": ">=180:80, 90-179:50, 30-89:20, else 0", "class": "OFFICIAL", "edge_cases": "negative balance -> 0 days"},
    {"rule_id": "R-3.1", "factor": "3.1", "name": "On-time Payment Rate", "input": "on_time_payment_rate", "thresholds": ">=98%:200, 95-97%:150, 90-94%:100, 80-89%:50, else 0", "class": "OFFICIAL", "edge_cases": "<6 bills -> 0; grace days = D1 (0)"},
    {"rule_id": "R-3.2", "factor": "3.2", "name": "Debt-to-Income Ratio", "input": "debt_to_income", "thresholds": "<=20%:120, 21-35%:80, 36-50%:40, else 0", "class": "OFFICIAL", "edge_cases": "no debt -> 0% -> 120"},
    {"rule_id": "R-3.3", "factor": "3.3", "name": "Credit Utilization", "input": "credit_utilization", "thresholds": "<=10%:100, 11-30%:70, 31-50%:30, else 0", "class": "OFFICIAL", "edge_cases": "no line -> neutral 70; unverified line -> provisional 70"},
    {"rule_id": "R-3.4", "factor": "3.4", "name": "Recent Delinquency Severity", "input": "delinquency_events", "thresholds": "none 150; one 30-59 100; one 60-89 50; one 90+ or multiple 0", "class": "OFFICIAL", "edge_cases": "counted per bill (D2); no bills -> 150 + flag"},
    {"rule_id": "R-4.1", "factor": "4.1", "name": "Positive Financial Behaviour", "input": "positive_habits", "thresholds": "+20 per habit, cap +50", "class": "OFFICIAL", "edge_cases": "habit definitions PROPOSED (D4)"},
    {"rule_id": "R-4.2", "factor": "4.2", "name": "Risk Flags", "input": "risk_flags", "thresholds": "-20 per flag, floor -50", "class": "OFFICIAL", "edge_cases": "flag definitions PROPOSED (D5)"},
]


def data_quality(features: dict, records: list) -> dict:
    flags = features["flags"]
    scored = [r for r in records if r["id"] not in ("4.1", "4.2")]
    measured = [r for r in scored if r["status"] in ("ok", "partial", "na", "thin")]
    coverage = len(measured) / len(scored)
    missing = [r["id"] for r in scored if r["status"] in ("missing", "insufficient", "unverified")]
    critical = any(f["severity"] == "critical" for f in flags)
    warnings = [f for f in flags if f["severity"] in ("warning", "critical")]
    if critical or coverage < 0.75:
        status = "POOR"
    elif warnings or coverage < 1:
        status = "LIMITED"
    else:
        status = "GOOD"
    return {"status": status, "coverage": round(coverage, 3), "missing_features": missing,
            "warnings": [f["message"] for f in flags], "flags": flags,
            "confidence": "high" if status == "GOOD" else ("medium" if status == "LIMITED" else "low")}


def evaluate(features: dict) -> dict:
    """Run all 14 official rules on a feature set and assemble the policy score."""
    records = [fn(features["factors"][fid]) for fid, fn in RULES]
    raw = sum(r["points"] for r in records)
    score = min(max(raw, P.SCORE_MIN), P.SCORE_MAX)
    tier = P.tier_for(score)
    for r in records:           # EX-02 strength / weakness classification
        if r["id"] == "4.1":
            r["effect"] = "positive" if r["points"] > 0 else "neutral"
        elif r["id"] == "4.2":
            r["effect"] = "negative" if r["points"] < 0 else "neutral"
        elif r["points"] >= 0.75 * r["max"]:
            r["effect"] = "positive"
        elif r["points"] <= 0.25 * r["max"]:
            r["effect"] = "negative"
        else:
            r["effect"] = "neutral"
        r["points_lost"] = (r["max"] - r["points"]) if r["id"] != "4.2" else -r["points"]
    components = {}
    for r in records:
        c = components.setdefault(r["component"], {"points": 0, "max": 0})
        c["points"] += r["points"]
        c["max"] += r["max"]
    dq = data_quality(features, records)
    flag_codes = {f["code"] for f in features["flags"]}
    return {
        "rule_version": P.RULE_VERSION,
        "as_of": features["as_of"],
        "score": int(score), "raw_score": int(raw), "capped": raw > P.SCORE_MAX, "floored": raw < P.SCORE_MIN,
        "tier": {"code": tier.code, "name": tier.name, "color": tier.color, "meaning": tier.meaning,
                 "min": tier.min_score, "max": tier.max_score},
        "positive_points": int(sum(r["points"] for r in records if r["points"] > 0)),
        "negative_points": int(sum(r["points"] for r in records if r["points"] < 0)),
        "points_lost": int(sum(r["points_lost"] for r in records)),
        "components": components,
        "factors": records,
        "income": features["income"],
        "data_quality": dq,
        "identity_blocked": "ID_UNVERIFIED" in flag_codes,
        "weak_id": "WEAK_ID" in flag_codes,
        "open_decisions": P.OPEN_DECISIONS,
    }
