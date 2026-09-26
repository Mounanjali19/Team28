"""Case 3: Target Achievement / counterfactual guidance (rules CF-01..CF-08).

"What is the minimum change in my features required to reach the target score?"

The search only uses *future, actionable* levers and runs every candidate
through the real simulator + rule engine, so each suggestion is verified
(CF-05). It never touches age, city, past transactions, past bills, past
delinquency or past employment (CF-02), and never suggests raising income,
buying a home or opening credit (CF-07).

Search order (CF-04): shortest horizon first; within a horizon, prefer no
action (waiting), then fewer levers, then lower effort, then the smallest
level of each lever.
"""
from __future__ import annotations

import json
from itertools import combinations

import numpy as np

from app.features.engineering import compute_features
from app.features.userdata import add_months, month_start
from app.rules import policy as P
from app.rules.engine import evaluate
from app.simulator.whatif import Scenario, score_at

EFFORT = {"wait": 0, "autopay": 1, "card_paydown": 1, "spend_cut": 2, "saving_boost": 2, "smooth_cashflow": 2, "recurring_investment": 3}


def _levers(features: dict) -> list[dict]:
    """Candidate levers with ascending levels; only those relevant to this applicant."""
    fx = features["factors"]
    income = features["income"]["value"]
    spend = fx["2.1"]["evidence"].get("avg_monthly_spend") or 0.0
    levers = []
    if fx["3.1"]["value"] is None or fx["3.1"]["value"] < 1.0 or fx["1.3"]["value"] is None or (fx["1.3"]["value"] or 0) < 1.0 \
            or fx["1.2"]["value"] == "rent_12m_broken_streak":
        levers.append({"type": "autopay", "levels": [{"bill_types": ["rent", "utility", "telecom", "emi", "card_min"]}],
                       "describe": lambda p: "Turn on autopay so every bill (rent, utilities, mobile/internet, EMIs, card) is paid on its due date"})
    if fx["2.1"]["value"] is not None or fx["2.2"]["value"] is not None:
        cut_levels = [c for c in (0.1, 0.2, 0.3, 0.4) if c <= P.SIMULATION["counterfactual_max_spend_cut"]]
        levers.append({"type": "spend_cut", "levels": [{"pct": c} for c in cut_levels],
                       "describe": lambda p: f"Cut dining and shopping spend by {int(p['pct'] * 100)}%"})
    if income and income > spend:
        surplus = income - spend
        amounts = sorted({int(round(surplus * s / 500.0) * 500) for s in (0.1, 0.2, 0.4, P.SIMULATION["counterfactual_max_saving_share"])} - {0})
        if amounts:
            levers.append({"type": "saving_boost", "levels": [{"amount": a, "months": 12} for a in amounts],
                           "describe": lambda p: f"Keep an extra Rs {p['amount']:,} a month in your account instead of spending it"})
    if fx["2.3"]["value"] is not None and fx["2.3"]["value"] > 0.05:
        levers.append({"type": "smooth_cashflow", "levels": [{}],
                       "describe": lambda p: "Keep monthly spending steady (spread large purchases) to reduce cash-flow volatility"})
    util = fx["3.3"]["value"]
    if util is not None and util > 0.10:
        levels = [{"target_utilization": t} for t in (0.30, 0.10) if util > t]
        levers.append({"type": "card_paydown", "levels": levels,
                       "describe": lambda p: f"Pay your card balance down to {int(p['target_utilization'] * 100)}% of the limit before the next statement"})
    if fx["4.1"]["value"] < 3 and not any(h["id"] == "PH-03" for h in fx["4.1"]["evidence"]["habits"]):
        amt = int(max(500, round(((income or 0) - spend) * 0.1 / 500.0) * 500)) if income else 500
        levers.append({"type": "recurring_investment", "levels": [{"amount": amt}], "min_horizon": 6,
                       "describe": lambda p: f"Start a monthly recurring investment (SIP/RD) of Rs {p['amount']:,}"})
    return levers


def _scen(combo):
    return [Scenario(l["type"], lv) for l, lv in combo]


def counterfactual(ud, as_of, target_product: dict, products: list[dict]) -> dict:
    as_of = month_start(np.datetime64(as_of, "D"))
    feats = compute_features(ud, as_of)
    current = evaluate(feats)
    target = int(target_product["min_score"])
    gap = target - current["score"]
    base = {"product": {"product_id": target_product["product_id"], "product_name": target_product["product_name"], "min_score": target},
            "current_score": current["score"], "target_score": target, "gap": max(gap, 0), "rule_version": P.RULE_VERSION,
            "immutable_never_changed": ["age", "city tier", "past transactions", "past bill payments", "past delinquency",
                                        "past employment and residence", "education (long-term only)"],
            "milestones": milestones(feats, as_of)}
    if gap <= 0:
        return base | {"status": "ALREADY_ELIGIBLE", "reachable": True,
                       "message": f"You already qualify for {target_product['product_name']} (score {current['score']} >= {target})."}
    if current["identity_blocked"]:
        return base | {"status": "BLOCKED", "reachable": False, "message": "Identity must be confirmed before any product can be offered."}
    levers = _levers(feats)
    evals = 0
    cache = {}

    def run(h, combo):
        nonlocal evals
        key = (h, tuple((l["type"], json.dumps(lv, sort_keys=True)) for l, lv in combo))
        if key not in cache:
            evals += 1
            rule, _ = score_at(ud, as_of, h, _scen(combo))
            cache[key] = rule
        return cache[key]

    found = None
    for h in P.SIMULATION["counterfactual_horizons"]:
        usable = [l for l in levers if h >= l.get("min_horizon", 1)]
        wait = run(h, [])
        if wait["score"] >= target:
            found = (h, [], wait)
            break
        best = None
        for k in range(1, min(3, len(usable)) + 1):
            for subset in combinations(usable, k):
                maxed = [(l, l["levels"][-1]) for l in subset]
                if run(h, maxed)["score"] < target:
                    continue
                # shrink each lever to its smallest sufficient level
                chosen = list(maxed)
                for i, (l, _) in enumerate(chosen):
                    for lv in l["levels"]:
                        trial = chosen[:i] + [(l, lv)] + chosen[i + 1:]
                        if run(h, trial)["score"] >= target:
                            chosen = trial
                            break
                effort = sum(EFFORT[l["type"]] for l, _ in chosen)
                intensity = sum(l["levels"].index(lv) for l, lv in chosen)
                cand = (effort, intensity, [x["type"] for x, _ in chosen], chosen)
                if best is None or cand[:3] < best[:3]:
                    best = cand
            if best:
                break
        if best:
            found = (h, best[3], run(h, best[3]))
            break
    if not found:
        h = P.SIMULATION["counterfactual_horizons"][-1]
        allmax = [(l, l["levels"][-1]) for l in levers]
        best_rule = run(h, allmax)
        reachable_products = [p for p in products if best_rule["score"] >= p["min_score"]]
        top = max(reachable_products, key=lambda p: p["min_score"]) if reachable_products else None
        return base | {"status": "UNREACHABLE_12M", "reachable": False, "evaluations": evals,
                       "best_reachable_score": best_rule["score"],
                       "best_reachable_product": {"product_id": top["product_id"], "product_name": top["product_name"]} if top else None,
                       "message": (f"{target_product['product_name']} is not reachable within 12 months with the changes you can make now. "
                                   f"With every available change you could reach about {best_rule['score']}"
                                   + (f", enough for {top['product_name']}." if top else "."))}
    h, chosen, rule = found
    baseline = run(h, [])
    steps = []
    for i, (l, lv) in enumerate(chosen):
        without = run(h, [c for j, c in enumerate(chosen) if j != i])
        steps.append({"lever": l["type"], "params": lv, "action": l["describe"](lv),
                      "expected_points": rule["score"] - without["score"], "effort": EFFORT[l["type"]]})
    factor_moves = [{"id": c["id"], "name": c["name"], "from": c["points"], "to": s["points"], "delta": s["points"] - c["points"],
                     "text": s["text"]} for c, s in zip(current["factors"], rule["factors"]) if s["points"] != c["points"]]
    wait_gain = baseline["score"] - current["score"]
    msg = (f"You need about +{gap} points to reach {target} for {target_product['product_name']}. "
           + (f"Keeping your current habits for {h} month(s) gets you there." if not chosen else
              f"This plan gets you to about {rule['score']} within {h} month(s)")
           + (f" ({wait_gain:+d} of that comes from time passing, e.g. longer job tenure or old late payments ageing out)." if chosen and wait_gain
              else ("." if chosen else "")))
    return base | {"status": "REACHABLE", "reachable": True, "horizon_months": h, "projected_score": rule["score"],
                   "projected_tier": rule["tier"], "baseline_score_at_horizon": baseline["score"], "time_effect_points": wait_gain,
                   "steps": steps, "factor_changes": factor_moves, "evaluations": evals, "message": msg,
                   "verified": True, "verification": "Every step was re-scored through the full rule engine on a hypothetical future (CF-05)."}


def milestones(features: dict, as_of) -> list[dict]:
    """CF-06: dated no-action milestones, conditional on clean behaviour."""
    fx = features["factors"]
    out = []
    for e in fx["3.4"]["evidence"]["event_list"]:
        out.append({"date": e["rolls_off"], "what": f"{e['bucket']} day late {e['type']} payment (due {e['due_date']}) leaves the 24-month window",
                    "factor": "3.4"})
    for f in fx["4.2"]["evidence"]["flags"]:
        out.append({"date": f["expires"], "what": f"Risk flag '{f['name']}' expires", "factor": "4.2"})
    ev = fx["1.1"]["evidence"]
    if ev["counted"]:
        for m in (6, 12, 24):
            if ev["tenure_months"] < m:
                out.append({"date": str(add_months(as_of, m - ev["tenure_months"])), "what": f"{m} months in current job", "factor": "1.1"})
                break
    return sorted([m for m in out if m["date"] >= str(as_of)], key=lambda m: m["date"])[:8]
