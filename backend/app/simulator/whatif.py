"""What-If simulator (rules WI-01..WI-06, WI-G1..WI-G5).

History is immutable: a simulation clones the applicant, keeps only records
dated before the as-of date, appends *hypothetical* future records (hyp=True)
and re-runs the unchanged rule engine at a later as-of date. Nothing is written
back to the applicant's stored data or score.

Projection baseline (status quo, documented assumption): each future month
repeats the applicant's own recent behaviour. Transactions replay the matching
month of the last 6 complete months; bills replay the same month of the last
12 months, including their payment timing (so a habitually late payer stays
late unless a scenario changes it). Card statements repeat the last statement.
No new inquiries or address changes occur unless a scenario adds them.
Scenario effects are reported both against today's score and against this
baseline at the same horizon, so the effect of the change is not confused with
the effect of time passing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.features.engineering import compute_features
from app.features.userdata import NAT, UserData, add_months, month_start
from app.rules import policy as P
from app.rules.engine import evaluate

SCENARIO_TYPES = ("saving_boost", "autopay", "overspend", "delinquency", "new_debt", "employment_change",
                  "spend_cut", "smooth_cashflow", "card_paydown", "recurring_investment")


@dataclass
class Scenario:
    type: str
    params: dict = field(default_factory=dict)


def _shift_days(dates: np.ndarray, src_month: np.datetime64, dst_month: np.datetime64) -> np.ndarray:
    """Move dates from one month to another keeping the day-of-month (clamped)."""
    out = []
    months = int((dst_month.astype("datetime64[M]") - src_month.astype("datetime64[M]")).astype(int))
    for d in dates:
        out.append(NAT if np.isnat(d) else add_months(d, months))
    return np.array(out, dtype="datetime64[D]")


def truncate(ud: UserData, as_of: np.datetime64) -> UserData:
    """Keep only what was known before as_of (bills keep their real payment date)."""
    u = ud.clone()
    m = u.txn["date"] < as_of
    u.txn = {k: v[m] for k, v in u.txn.items()}
    m = u.obl["due"] < as_of
    u.obl = {k: v[m] for k, v in u.obl.items()}
    m = u.stmt["date"] < as_of
    u.stmt = {k: v[m] for k, v in u.stmt.items()}
    m = u.life["date"] < as_of
    u.life = {k: v[m] for k, v in u.life.items()}
    u.accounts = [a for a in u.accounts if not np.isnat(a["open"]) and a["open"] < as_of]
    u.employment = [s for s in u.employment if s["start"] < as_of]
    u.residence = [s for s in u.residence if s["start"] < as_of]
    return u


def _income(ud, as_of):
    feats = compute_features(ud, as_of)
    return feats["income"]["value"], feats


def project(ud: UserData, as_of, horizon: int, scenarios: list[Scenario]) -> tuple[UserData, np.datetime64, list[str]]:
    """Build the hypothetical applicant `horizon` months after as_of."""
    as_of = month_start(np.datetime64(as_of, "D"))
    base = truncate(ud, as_of)
    notes: list[str] = []
    income, _ = _income(base, as_of)
    am = as_of.astype("datetime64[M]")
    sc = {s.type: s.params for s in scenarios}

    # ---- employment / debt scenarios that change static records ----
    if "employment_change" in sc:
        for s in base.employment:
            if np.isnat(s["end"]) or s["end"] > as_of:
                s["end"] = as_of
        base.employment.append({"employment_type": sc["employment_change"].get("employment_type", "salaried"), "start": as_of,
                                "end": NAT, "declared_income": sc["employment_change"].get("monthly_income"), "hyp": True})
        if sc["employment_change"].get("monthly_income"):
            base.monthly_income = float(sc["employment_change"]["monthly_income"])
            income = base.monthly_income
        notes.append("New job starts today; employment stability counts months from the new start date (it cannot be back-dated).")
    if "new_debt" in sc:
        p = sc["new_debt"]
        emi = float(p.get("emi", 2000))
        acc_id = "HYP_LOAN"
        base.accounts.append({"account_id": acc_id, "account_type": "card" if p.get("revolving") else "loan",
                              "limit": float(p.get("limit", emi * 12)), "emi": emi, "open": as_of, "close": NAT, "hyp": True})
        base.append_life({"type": ["credit_inquiry"], "date": [as_of], "hyp": [True]})
        notes.append(f"New {'credit line' if p.get('revolving') else 'loan'} with Rs {emi:,.0f}/month repayment and one credit inquiry.")

    # ---- replay months ----
    hist_t, hist_o = base.txn, base.obl
    t_month = hist_t["date"].astype("datetime64[M]")
    o_month = hist_o["due"].astype("datetime64[M]")
    has_ledger = bool(len(hist_t["balance"])) and not np.isnan(hist_t["balance"][-1])
    last_balance = float(hist_t["balance"][-1]) if has_ledger else 0.0
    # source months for the status-quo replay (fall back to whatever recent months exist)
    recent = [am - k for k in range(6, 0, -1)]
    have_t = set(np.unique(t_month))
    txn_sources = [x for x in recent if x in have_t] or sorted(have_t)[-6:]
    have_o = set(np.unique(o_month))
    bill_fallback = sorted(x for x in have_o if x < am)[-12:]
    smooth = "smooth_cashflow" in sc
    if smooth and txn_sources:
        sel = np.isin(t_month, txn_sources)
        avg_debit = float(hist_t["amount"][sel & ~hist_t["is_credit"]].sum()) / len(txn_sources)
        avg_credit = float(hist_t["amount"][sel & hist_t["is_credit"]].sum()) / len(txn_sources)
        notes.append("Cash flow smoothed: the same total spending and income, spread evenly so every month looks alike.")
    new_t = {k: [] for k in hist_t}
    new_o = {k: [] for k in hist_o}
    delinquency_applied = {"utility": False, "rent": False}
    for m in range(horizon):
        tgt = am + m
        src = txn_sources[m % len(txn_sources)] if txn_sources else am - 1
        sel = t_month == src
        dates = _shift_days(hist_t["date"][sel], src, tgt)
        amt = hist_t["amount"][sel].astype(float).copy()
        cat = hist_t["category"][sel].copy()
        credit = hist_t["is_credit"][sel].copy()
        sub = hist_t["subtype"][sel].copy()
        if smooth:
            deb, cre = amt[~credit].sum(), amt[credit].sum()
            if deb > 0:
                amt[~credit] *= avg_debit / deb
            if cre > 0:
                amt[credit] *= avg_credit / cre
        disc = np.isin(cat, ["Dining", "Shopping"]) & ~credit
        if "spend_cut" in sc:
            amt[disc] *= (1 - float(sc["spend_cut"].get("pct", 0.2)))
        if "saving_boost" in sc and m < int(sc["saving_boost"].get("months", 3)):
            keep = float(sc["saving_boost"].get("amount", P.SIMULATION["saving_boost_default_amount"]))
            pool = np.isin(cat, ["Dining", "Shopping", "Cash Withdrawal"]) & ~credit
            total = amt[pool].sum()
            if total > 0:
                amt[pool] *= max(0.0, 1 - keep / total)
            if total < keep and m == 0:
                notes.append("Not enough discretionary spending to retain the full amount; retained what was available.")
        if "overspend" in sc and m < int(sc["overspend"].get("months", P.SIMULATION["overspend_default_months"])) and income:
            target = float(sc["overspend"].get("share", P.SIMULATION["overspend_default_share"])) * income
            cur = amt[disc].sum()
            if cur > 0:
                amt[disc] *= target / cur
            else:
                dates = np.append(dates, tgt.astype("datetime64[D]") + 14)
                amt = np.append(amt, target)
                cat = np.append(cat, "Shopping")
                credit = np.append(credit, False)
                sub = np.append(sub, "")
        if "recurring_investment" in sc:
            inv = float(sc["recurring_investment"].get("amount", 1000))
            dates = np.append(dates, tgt.astype("datetime64[D]") + 4)
            amt = np.append(amt, inv)
            cat = np.append(cat, "Savings")
            credit = np.append(credit, False)
            sub = np.append(sub, "recurring_investment")
        if "new_debt" in sc:
            emi = float(sc["new_debt"].get("emi", 2000))
            dates = np.append(dates, tgt.astype("datetime64[D]") + 4)
            amt = np.append(amt, emi)
            cat = np.append(cat, "Loan EMI")
            credit = np.append(credit, False)
            sub = np.append(sub, "")
        if "employment_change" in sc and sc["employment_change"].get("monthly_income"):
            # replace income credits with the new salary
            keep_mask = ~(credit & np.isin(cat, list(P.INCOME_CATEGORIES)))
            dates, amt, cat, credit, sub = dates[keep_mask], amt[keep_mask], cat[keep_mask], credit[keep_mask], sub[keep_mask]
            dates = np.append(dates, tgt.astype("datetime64[D]"))
            amt = np.append(amt, float(sc["employment_change"]["monthly_income"]))
            cat = np.append(cat, "Salary")
            credit = np.append(credit, True)
            sub = np.append(sub, "")
        order = np.argsort(dates, kind="stable")
        dates, amt, cat, credit, sub = dates[order], amt[order], cat[order], credit[order], sub[order]
        signed = np.where(credit, amt, -amt)
        bal = last_balance + np.cumsum(signed) if has_ledger else np.full(len(signed), np.nan)
        if len(bal) and has_ledger:
            last_balance = float(bal[-1])
        for k, v in (("date", dates), ("amount", amt), ("category", cat), ("is_credit", credit), ("balance", bal), ("subtype", sub),
                     ("hyp", np.ones(len(dates), bool))):
            new_t[k].append(v)

        # bills: same month last year, same payment timing
        osrc = am - 12 + (m % 12)
        if osrc not in have_o and bill_fallback:
            osrc = bill_fallback[m % len(bill_fallback)]
        osel = o_month == osrc
        due = _shift_days(hist_o["due"][osel], osrc, tgt)
        lag = np.where(np.isnat(hist_o["paid"][osel]), -1,
                       (hist_o["paid"][osel] - hist_o["due"][osel]).astype("timedelta64[D]").astype(np.int64))
        types = hist_o["type"][osel].copy()
        amt_due = hist_o["amount_due"][osel].copy()
        autopay = hist_o["autopay"][osel].copy()
        acct = hist_o["account"][osel].copy()
        if "autopay" in sc:
            on = set(sc["autopay"].get("bill_types", ["rent", "utility", "telecom", "emi", "card_min"]))
            hit = np.isin(types, list(on))
            lag = np.where(hit, 0, lag)
            autopay = np.where(hit, True, autopay)
        if "new_debt" in sc:
            due = np.append(due, tgt.astype("datetime64[D]") + 4)
            lag = np.append(lag, 0)
            types = np.append(types, "emi")
            amt_due = np.append(amt_due, float(sc["new_debt"].get("emi", 2000)))
            autopay = np.append(autopay, False)
            acct = np.append(acct, "HYP_LOAN")
        if "delinquency" in sc and m == 0:
            p = sc["delinquency"]
            ut_days = int(p.get("utility_days", P.SIMULATION["delinquency_utility_days"]))
            rent_days = int(p.get("rent_days", P.SIMULATION["delinquency_rent_days"]))
            for kind, days in (("utility", ut_days), ("rent", rent_days)):
                if days <= 0:
                    continue
                cands = np.flatnonzero(types == kind) if kind == "rent" else np.flatnonzero(np.isin(types, ["utility", "telecom"]))
                if len(cands):
                    lag[cands[0]] = days
                    delinquency_applied[kind] = str(types[cands[0]])
            if not delinquency_applied["rent"] and rent_days > 0:
                notes.append("You have no rent bill, so the late-rent part of this scenario does not apply.")
            if not delinquency_applied["utility"] and ut_days > 0:
                notes.append("No utility or telecom bill found to delay.")
        paid = np.array([NAT if l < 0 else d + int(l) for d, l in zip(due, lag)], dtype="datetime64[D]")
        for k, v in (("type", types), ("due", due), ("paid", paid), ("amount_due", amt_due), ("autopay", autopay),
                     ("account", acct), ("hyp", np.ones(len(due), bool))):
            new_o[k].append(v)

    if horizon:
        base.append_txn({k: np.concatenate(v) if v else [] for k, v in new_t.items()})
        base.append_obl({k: np.concatenate(v) if v else [] for k, v in new_o.items()})
        # card statements repeat the last one (or the paydown target)
        for a in base.accounts:
            if a["account_type"] not in P.REVOLVING_ACCOUNT_TYPES:
                continue
            sel = np.flatnonzero(base.stmt["account"] == a["account_id"])
            if len(sel) == 0 and not a.get("hyp"):
                continue
            last_lim = float(base.stmt["limit"][sel[-1]]) if len(sel) else a["limit"]
            last_out = float(base.stmt["outstanding"][sel[-1]]) if len(sel) else float(sc.get("new_debt", {}).get("drawn", 0.5 * a["limit"]))
            if "card_paydown" in sc:
                last_out = min(last_out, float(sc["card_paydown"].get("target_utilization", 0.3)) * last_lim)
            dates = [((am + m + 1).astype("datetime64[D]") - 1) for m in range(horizon)]
            base.append_stmt({"account": [a["account_id"]] * horizon, "date": dates, "limit": [last_lim] * horizon,
                              "outstanding": [last_out] * horizon, "min_due": [max(200.0, 0.05 * last_out)] * horizon,
                              "hyp": [True] * horizon})
    base.sort()
    new_as_of = add_months(as_of, horizon)
    if "autopay" in sc:
        notes.append("Autopay pays every selected bill on its due date from now on; past late payments stay on record.")
    if "delinquency" in sc:
        notes.append("Late payments are applied to bills due this month; effects are measured once they are that late.")
    return base, new_as_of, notes


def _summary(rule):
    return {"score": rule["score"], "raw_score": rule["raw_score"], "tier": rule["tier"],
            "factors": {r["id"]: {"points": r["points"], "value_display": r["value_display"], "text": r["text"]} for r in rule["factors"]}}


def score_at(ud: UserData, as_of, horizon: int, scenarios: list[Scenario]) -> tuple[dict, list]:
    hyp, new_as_of, notes = project(ud, as_of, horizon, scenarios)
    return evaluate(compute_features(hyp, new_as_of)), notes


def simulate(ud: UserData, as_of, scenarios: list[Scenario], horizon: int | None, products: list[dict]) -> dict:
    horizon = int(horizon if horizon is not None else _default_horizon(scenarios))
    horizon = max(1, min(horizon, P.SIMULATION["max_horizon_months"]))
    current = evaluate(compute_features(ud, as_of))
    baseline, _ = score_at(ud, as_of, horizon, [])
    simulated, notes = score_at(ud, as_of, horizon, scenarios)

    def elig(score):
        return {p["product_id"] for p in products if score >= p["min_score"]}

    cur_e, sim_e, base_e = elig(current["score"]), elig(simulated["score"]), elig(baseline["score"])
    name = {p["product_id"]: p["product_name"] for p in products}
    changes = []
    for c, b, s in zip(current["factors"], baseline["factors"], simulated["factors"]):
        changes.append({"id": c["id"], "name": c["name"], "current_points": c["points"], "baseline_points": b["points"],
                        "simulated_points": s["points"], "delta_vs_current": s["points"] - c["points"],
                        "delta_vs_baseline": s["points"] - b["points"], "current_value": c["value_display"],
                        "simulated_value": s["value_display"], "simulated_text": s["text"]})
    return {
        "hypothetical": True,
        "scenarios": [{"type": s.type, "params": s.params} for s in scenarios],
        "horizon_months": horizon, "as_of": str(as_of), "simulated_as_of": str(add_months(month_start(np.datetime64(as_of, "D")), horizon)),
        "current": {"score": current["score"], "tier": current["tier"], "eligible_products": sorted(cur_e)},
        "baseline": {"score": baseline["score"], "tier": baseline["tier"], "eligible_products": sorted(base_e),
                     "label": f"If nothing changes, in {horizon} month(s)"},
        "simulated": {"score": simulated["score"], "raw_score": simulated["raw_score"], "tier": simulated["tier"],
                      "eligible_products": sorted(sim_e)},
        "delta_vs_current": simulated["score"] - current["score"],
        "delta_vs_baseline": simulated["score"] - baseline["score"],
        "raw_delta_vs_current": simulated["raw_score"] - current["raw_score"],
        "tier_change": None if simulated["tier"]["code"] == current["tier"]["code"] else f"{current['tier']['name']} -> {simulated['tier']['name']}",
        "products_gained": [{"product_id": p, "product_name": name[p]} for p in sorted(sim_e - cur_e)],
        "products_lost": [{"product_id": p, "product_name": name[p]} for p in sorted(cur_e - sim_e)],
        "factor_changes": changes,
        "changed_factors": [c for c in changes if c["delta_vs_current"] != 0 or c["delta_vs_baseline"] != 0],
        "notes": notes + ["Assumes everything else continues as in your recent months (status-quo projection)."]
                 + (["Score is capped at 1000: raw points moved even where the final score cannot."] if current["capped"] or simulated["capped"] else []),
        "rule_version": P.RULE_VERSION,
    }


def _default_horizon(scenarios):
    types = {s.type for s in scenarios}
    if "delinquency" in types:
        return 2
    if "overspend" in types:
        return 2
    if "employment_change" in types:
        return 6
    if "new_debt" in types:
        return 1
    return P.SIMULATION["default_horizon_months"]


PRESETS = {
    "saving_boost": {"title": "Saving Buffer Boost", "description": "Save an extra Rs 1,000 a month for 3 months",
                     "scenarios": [{"type": "saving_boost", "params": {"amount": 1000, "months": 3}}], "horizon": 3,
                     "official_example": "+35 points (illustrative)", "factors": ["2.4", "2.3"]},
    "autopay": {"title": "Utility & Rent Consistency Builder", "description": "Turn on autopay for rent and utility bills",
                "scenarios": [{"type": "autopay", "params": {"bill_types": ["rent", "utility", "telecom"]}}], "horizon": 3,
                "official_example": "+60 points (illustrative)", "factors": ["3.1", "1.2"]},
    "overspend": {"title": "Discretionary Overspend", "description": "Spend 75% of income on dining and shopping for 2 months",
                  "scenarios": [{"type": "overspend", "params": {"share": 0.75, "months": 2}}], "horizon": 2,
                  "official_example": "-50 points (illustrative)", "factors": ["2.1", "2.2", "2.3"]},
    "delinquency": {"title": "Utility and Rent Delinquency", "description": "Pay a utility/internet bill 45 days late and rent 15 days late",
                    "scenarios": [{"type": "delinquency", "params": {"utility_days": 45, "rent_days": 15}}], "horizon": 2,
                    "official_example": "-110 points (illustrative), pre-approved card revoked", "factors": ["3.4", "3.1"]},
    "new_debt": {"title": "Take Additional Debt", "description": "Take a new loan with a Rs 5,000 monthly EMI",
                 "scenarios": [{"type": "new_debt", "params": {"emi": 5000}}], "horizon": 1, "official_example": None, "factors": ["3.2", "4.2"]},
    "employment_change": {"title": "Gain Steady Employment", "description": "Start a salaried job today (tenure builds from zero)",
                          "scenarios": [{"type": "employment_change", "params": {"employment_type": "salaried"}}], "horizon": 12,
                          "official_example": None, "factors": ["1.1"]},
}
