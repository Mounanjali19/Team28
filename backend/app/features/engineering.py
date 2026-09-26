"""Feature engineering for the 14 official rule sub-factors.

``compute_features(user, as_of)`` reads only records dated strictly before
``as_of`` (rule T-02) and returns, for every sub-factor, the measured value,
its data status and the evidence that produced it. The rule engine turns these
into points; the ML layer reads the same measured values (never the points).

Every feature is documented in ``FEATURE_CATALOG`` (definition, source,
formula, window, missing-data behaviour) and served by ``GET /api/features/catalog``.
"""
from __future__ import annotations

import math

import numpy as np

from app.rules import policy as P
from app.features.userdata import UserData, add_months, full_months_between, month_start, NAT

FEATURE_CATALOG = {
    "1.1": {"feature": "employment_tenure_months", "definition": "Full calendar months in the current job (gig/freelance: continuous months with platform or client income)",
            "source": "employment_spells, transactions (income credits)", "formula": "months(spell.start -> as_of); gig: min(spell months, consecutive income months)",
            "window": "point-in-time", "missing": "no open spell or student/unemployed -> 0 months"},
    "1.2": {"feature": "housing_state", "definition": "Housing status and, for renters, 12-month on-time rent streak",
            "source": "residence_spells, obligations(rent)", "formula": "own; rent with >=12 mo residence and last 12 rent bills on time; rent <12 mo; family; none",
            "window": "12 most recent rent bills", "missing": "status missing -> 0 + HOUSING_MISSING"},
    "1.3": {"feature": "telecom_on_time_month_share", "definition": "Share of months (with a mobile/internet bill) in which every such bill was paid on or before its due date",
            "source": "obligations(telecom)", "formula": "on-time months / months with a telecom bill", "window": "last 12 months",
            "missing": "<6 months with a bill -> 0 + INSUFFICIENT_HISTORY"},
    "1.4": {"feature": "education_level", "definition": "Highest credential", "source": "demographics", "formula": "lookup",
            "window": "point-in-time", "missing": "missing -> 0 + EDUCATION_MISSING"},
    "2.1": {"feature": "spend_to_income", "definition": "Average monthly consumption spend / monthly income",
            "source": "transactions, demographics", "formula": "sum(consumption debits)/months / income", "window": "6 complete calendar months",
            "missing": "income missing -> 0 + INCOME_MISSING; <3 months -> 0 + INSUFFICIENT_HISTORY"},
    "2.2": {"feature": "essential_share", "definition": "Essentials / (essentials + dining + shopping + charity)",
            "source": "transactions", "formula": "essential debits / classified debits", "window": "6 complete calendar months",
            "missing": "no classified spend -> 0 + INSUFFICIENT_HISTORY"},
    "2.3": {"feature": "cashflow_volatility", "definition": "Population std-dev of monthly net cash flow / monthly income",
            "source": "transactions", "formula": "std(credits - debits per month) / income", "window": "6 complete calendar months",
            "missing": "<3 months -> 0 + INSUFFICIENT_HISTORY; income missing -> 0"},
    "2.4": {"feature": "days_of_income_saved", "definition": "Liquid balance expressed in days of income",
            "source": "transactions.balance_after", "formula": "floor(balance / (income / 30))", "window": "point-in-time",
            "missing": "no ledger -> 0; negative balance -> 0 days + NEGATIVE_BALANCE"},
    "3.1": {"feature": "on_time_payment_rate", "definition": "Bills paid on or before due date / bills due (rent, utility, telecom, EMI, card minimum)",
            "source": "obligations", "formula": "count(paid - due <= grace) / count(due)", "window": "last 12 months",
            "missing": "<6 bills -> 0 + INSUFFICIENT_HISTORY; missing bill types -> computed over available types"},
    "3.2": {"feature": "debt_to_income", "definition": "Monthly EMI + card minimum due / monthly income",
            "source": "obligations(emi, card_min)", "formula": "mean monthly debt due / income", "window": "3 complete calendar months",
            "missing": "no debt -> 0%; income missing -> 0 + INCOME_MISSING"},
    "3.3": {"feature": "credit_utilization", "definition": "Outstanding balance / credit limit over open revolving lines",
            "source": "credit_accounts, card_statements", "formula": "sum(outstanding) / sum(limit), latest statement per line",
            "window": "latest statement before as-of", "missing": "no line -> N/A (neutral 70); line without statement -> provisional 70"},
    "3.4": {"feature": "delinquency_events", "definition": "Bills 30+ days past due, bucketed 30-59 / 60-89 / 90+",
            "source": "obligations", "formula": "count and worst bucket of bills with dpd >= 30", "window": "last 24 months",
            "missing": "no bills -> 150 (literal) + THIN_REPAYMENT_HISTORY"},
    "4.1": {"feature": "positive_habits", "definition": "Micro-savings in >=9/12 months, charity in >=4/12 months, recurring investment >=6 consecutive months",
            "source": "transactions(Savings subtype, Charity)", "formula": "+20 per habit, cap +50", "window": "12 complete months",
            "missing": "no transactions -> 0 habits"},
    "4.2": {"feature": "risk_flags", "definition": "Address change in last 12 months; 2+ credit inquiries in last 6 months",
            "source": "life_events", "formula": "-20 per flag, floor -50", "window": "12 / 6 months", "missing": "no events -> 0 flags"},
}

FLAG_MESSAGES = {
    "INCOME_MISSING": "No declared or verifiable income; income-based factors (2.1, 2.3, 2.4, 3.2) score 0.",
    "INCOME_VERIFIED": "Declared income missing; income verified from salary/business/gig credits instead.",
    "INCOME_CONFLICT": "Declared income is more than 1.5x verified income credits; verified income used.",
    "EMPLOYMENT_MISSING": "No current employment record; employment stability scores 0.",
    "HOUSING_MISSING": "Housing status unavailable; housing factor scores 0 pending review.",
    "RENT_UNVERIFIED": "Renter with no rent payment records; rent streak could not be verified.",
    "EDUCATION_MISSING": "Education not provided; education factor scores 0.",
    "TELECOM_INSUFFICIENT": "Fewer than 6 months of mobile/internet bills; digital footprint scores 0.",
    "UTILITY_HISTORY_MISSING": "Utility payment history unavailable; on-time rate calculated from the other bill types.",
    "INSUFFICIENT_HISTORY": "Fewer than 3 complete months of transactions; spending factors score 0.",
    "PARTIAL_WINDOW": "Transaction window partially covered (3-5 of 6 months); spending factors use available months.",
    "BILLS_INSUFFICIENT": "Fewer than 6 bills due in the last 12 months; on-time payment rate scores 0.",
    "THIN_REPAYMENT_HISTORY": "No bills in the last 24 months; delinquency factor uses the literal 'no delinquency' band.",
    "NO_CREDIT_LINE": "No revolving credit line; utilization does not apply and scores the neutral 70.",
    "UTILIZATION_UNVERIFIED": "Credit line without a statement yet; utilization provisionally scored 70.",
    "OVERLIMIT": "Card balance exceeds the credit limit.",
    "NEGATIVE_BALANCE": "Account balance is negative; savings buffer counted as 0 days.",
    "IMPLAUSIBLE_SPEND": "Spending exceeds 300% of income; flagged for review.",
    "WEAK_ID": "Identity match confidence below 0.8; offers withheld until confirmed.",
    "ID_UNVERIFIED": "Identity match confidence below 0.6; application referred to manual review.",
    "DEMOGRAPHIC_CONFLICT": "Declared housing/employment differs from dated records; dated records used.",
}
FLAG_SEVERITY = {
    "INCOME_VERIFIED": "info", "NO_CREDIT_LINE": "info", "UTILITY_HISTORY_MISSING": "info",
    "PARTIAL_WINDOW": "warning", "DEMOGRAPHIC_CONFLICT": "info", "THIN_REPAYMENT_HISTORY": "warning",
    "ID_UNVERIFIED": "critical", "INCOME_MISSING": "critical", "INSUFFICIENT_HISTORY": "critical",
}


def _flag(flags: list, code: str, factor: str | None = None):
    if not any(f["code"] == code for f in flags):
        flags.append({"code": code, "severity": FLAG_SEVERITY.get(code, "warning"), "factor": factor,
                      "message": FLAG_MESSAGES[code]})


def _on_time(due, paid, as_of):
    """Paid on/before due (+grace) and before the as-of date (rule T-03)."""
    paid_known = ~np.isnat(paid)
    paid_before = paid_known & (paid < as_of)
    lag = np.where(paid_before, (paid - due).astype("timedelta64[D]").astype(np.int64), 10**6)
    return paid_before & (lag <= P.GRACE_DAYS)


def _dpd_as_of(due, paid, as_of):
    paid_before = ~np.isnat(paid) & (paid < as_of)
    end = np.where(paid_before, paid, as_of)
    return np.maximum((end - due).astype("timedelta64[D]").astype(np.int64), 0)


def _current_spell(spells: list, as_of):
    open_ = [s for s in spells if not np.isnat(s["start"]) and s["start"] <= as_of
             and (np.isnat(s["end"]) or s["end"] > as_of)]
    if not open_:
        return None
    return max(open_, key=lambda s: s["start"])


def compute_features(user: UserData, as_of) -> dict:
    as_of = month_start(np.datetime64(as_of, "D"))
    as_of_m = as_of.astype("datetime64[M]")
    flags: list = []
    factors: dict = {}

    tx = user.txn
    tmask = tx["date"] < as_of
    t_date, t_amt, t_cat = tx["date"][tmask], tx["amount"][tmask], tx["category"][tmask]
    t_credit, t_bal, t_sub = tx["is_credit"][tmask], tx["balance"][tmask], tx["subtype"][tmask]
    valid = t_amt > 0
    t_date, t_amt, t_cat, t_credit, t_bal, t_sub = (a[valid] for a in (t_date, t_amt, t_cat, t_credit, t_bal, t_sub))
    t_month = t_date.astype("datetime64[M]")
    t_mi = t_month.astype(np.int64)          # integer month index for set logic
    as_of_mi = int(as_of_m.astype(np.int64))

    ob = user.obl
    omask = ob["due"] < as_of
    o_type, o_due, o_paid, o_amt = ob["type"][omask], ob["due"][omask], ob["paid"][omask], ob["amount_due"][omask]
    o_ontime = _on_time(o_due, o_paid, as_of)

    # ---------------- income resolution (MD-01, MD-11) ----------------
    n_inc = P.WINDOWS["income_verify_months"]
    inc_start = (as_of_m - n_inc)
    in_inc = (t_month >= inc_start) & t_credit & np.isin(t_cat, list(P.INCOME_CATEGORIES))
    months_with_data_inc = len(np.unique(t_month[(t_month >= inc_start)]))
    verified_income = float(t_amt[in_inc].sum() / max(months_with_data_inc, 1)) if months_with_data_inc else 0.0
    declared = user.monthly_income if user.monthly_income and user.monthly_income > 0 else None
    if declared:
        if verified_income > 0 and declared > P.INCOME_CONFLICT_RATIO * verified_income:
            income, income_source = verified_income, "verified"
            _flag(flags, "INCOME_CONFLICT")
        else:
            income, income_source = float(declared), "declared"
    elif verified_income > 0:
        income, income_source = verified_income, "verified"
        _flag(flags, "INCOME_VERIFIED")
    else:
        income, income_source = None, "missing"
        _flag(flags, "INCOME_MISSING")

    # income volatility index (advanced feature, ML only)
    inc_months = [t_amt[(t_month == m) & t_credit & np.isin(t_cat, list(P.INCOME_CATEGORIES))].sum()
                  for m in (as_of_m - k for k in range(6, 0, -1))]
    inc_mean = float(np.mean(inc_months))
    income_cv = float(np.std(inc_months) / inc_mean) if inc_mean > 0 else None

    # ---------------- 1.1 Employment stability ----------------
    spell = _current_spell(user.employment, as_of)
    emp_type = spell["employment_type"] if spell else None
    spell_months = full_months_between(spell["start"], as_of) if spell else 0
    if spell is None:
        tenure, status = 0, "missing"
        _flag(flags, "EMPLOYMENT_MISSING", "1.1")
    elif emp_type not in P.EMPLOYMENT_TYPES_COUNTED:
        tenure, status = 0, "ok"
    elif emp_type in P.GIG_TYPES:
        income_months = set(t_mi[t_credit & np.isin(t_cat, list(P.INCOME_CATEGORIES))].tolist())
        consecutive, m = 0, as_of_mi - 1
        while m in income_months:
            consecutive += 1
            m -= 1
        tenure, status = min(spell_months, consecutive), "ok"
    else:
        tenure, status = spell_months, "ok"
    if user.employment_status and emp_type and user.employment_status != emp_type and user.source == "altcredit_v2":
        _flag(flags, "DEMOGRAPHIC_CONFLICT", "1.1")
    factors["1.1"] = {"value": tenure, "status": status,
                      "evidence": {"employment_type": emp_type, "spell_months": spell_months, "tenure_months": tenure,
                                   "spell_start": str(spell["start"]) if spell else None,
                                   "counted": emp_type in P.EMPLOYMENT_TYPES_COUNTED if emp_type else False}}

    # ---------------- 1.2 Housing status ----------------
    res = _current_spell(user.residence, as_of)
    housing = res["housing_status"] if res else (user.housing_status or None)
    res_months = full_months_between(res["start"], as_of) if res else 0
    rent_mask = o_type == "rent"
    rent_ontime = o_ontime[rent_mask]
    last12 = rent_ontime[-P.HOUSING_STREAK_MONTHS:]
    streak = 0
    for ok in rent_ontime[::-1]:
        if not ok:
            break
        streak += 1
    h_status = "ok"
    if not housing:
        state, h_status = "missing", "missing"
        _flag(flags, "HOUSING_MISSING", "1.2")
    elif housing == "own":
        state = "own"
    elif housing == "family":
        state = "family"
    elif housing == "rent":
        if res_months >= P.HOUSING_STREAK_MONTHS and len(last12) >= P.HOUSING_STREAK_MONTHS and last12.all():
            state = "rent_12m_on_time"
        elif rent_mask.sum() == 0:
            state = "rent_short"
            _flag(flags, "RENT_UNVERIFIED", "1.2")
        elif res_months >= P.HOUSING_STREAK_MONTHS:
            state = "rent_12m_broken_streak"
        else:
            state = "rent_short"
    else:
        state = "none"
    if res and user.housing_status and user.housing_status != res["housing_status"]:
        _flag(flags, "DEMOGRAPHIC_CONFLICT", "1.2")
    factors["1.2"] = {"value": state, "status": h_status,
                      "evidence": {"housing_status": housing, "residence_months": res_months,
                                   "rent_streak_months": streak, "rent_bills_last12": int(len(last12)),
                                   "rent_late_last12": int((~last12).sum()) if len(last12) else 0}}

    # ---------------- 1.3 Digital footprint ----------------
    w12 = add_months(as_of, -P.WINDOWS["digital_footprint_months"])
    tel = (o_type == "telecom") & (o_due >= w12)
    tel_months = o_due[tel].astype("datetime64[M]")
    months = np.unique(tel_months)
    ok_months = sum(bool(o_ontime[tel][tel_months == m].all()) for m in months)
    if len(months) < P.MIN_TELECOM_MONTHS:
        share, status = None, "insufficient"
        _flag(flags, "TELECOM_INSUFFICIENT", "1.3")
    else:
        share, status = ok_months / len(months), "ok"
    factors["1.3"] = {"value": share, "status": status,
                      "evidence": {"months_with_bill": int(len(months)), "on_time_months": int(ok_months)}}

    # ---------------- 1.4 Education ----------------
    edu_raw = (user.education_level or "").strip().lower()
    edu = P.EDUCATION_ALIASES.get(edu_raw, edu_raw if edu_raw in P.EDUCATION_POINTS else None)
    if edu is None:
        _flag(flags, "EDUCATION_MISSING", "1.4")
    factors["1.4"] = {"value": edu, "status": "ok" if edu else "missing", "evidence": {"education_level": edu}}

    # ---------------- spending window (2.1 / 2.2 / 2.3) ----------------
    n6 = P.WINDOWS["spend_complete_months"]
    s_start = as_of_m - n6
    in6 = t_month >= s_start
    months6 = np.unique(t_month[in6])
    n_months = len(months6)
    if n_months < P.MIN_COMPLETE_TXN_MONTHS:
        _flag(flags, "INSUFFICIENT_HISTORY", "2.x")
        window_status = "insufficient"
    else:
        window_status = "ok" if n_months >= n6 else "partial"
        if window_status == "partial":
            _flag(flags, "PARTIAL_WINDOW", "2.x")
    debit6 = in6 & ~t_credit
    consumption = float(t_amt[debit6 & np.isin(t_cat, list(P.CONSUMPTION_CATEGORIES))].sum())
    avg_spend = consumption / n_months if n_months else 0.0
    essential = float(t_amt[debit6 & np.isin(t_cat, list(P.ESSENTIAL_CATEGORIES))].sum())
    discretionary = float(t_amt[debit6 & np.isin(t_cat, list(P.DISCRETIONARY_CATEGORIES))].sum())
    lifestyle = float(t_amt[debit6 & np.isin(t_cat, list(P.LIFESTYLE_CATEGORIES))].sum())

    # 2.1
    if window_status == "insufficient":
        sti, st = None, "insufficient"
    elif income is None:
        sti, st = None, "missing"
    else:
        sti, st = avg_spend / income, window_status
        if sti > 3:
            _flag(flags, "IMPLAUSIBLE_SPEND", "2.1")
    factors["2.1"] = {"value": sti, "status": st,
                      "evidence": {"avg_monthly_spend": round(avg_spend, 2), "monthly_income": income,
                                   "income_source": income_source, "months": n_months}}
    # 2.2
    denom = essential + discretionary
    if window_status == "insufficient" or denom <= 0:
        ess, st = None, "insufficient"
    else:
        ess, st = essential / denom, window_status
    factors["2.2"] = {"value": ess, "status": st,
                      "evidence": {"essential_spend": round(essential, 2), "discretionary_spend": round(discretionary, 2),
                                   "months": n_months}}
    # 2.3
    nets = []
    for m in months6:
        sel = t_month == m
        nets.append(float(t_amt[sel & t_credit].sum() - t_amt[sel & ~t_credit].sum()))
    sigma = float(np.std(nets)) if nets else None
    if window_status == "insufficient":
        vol, st = None, "insufficient"
    elif income is None:
        vol, st = None, "missing"
    else:
        vol, st = sigma / income, window_status
    factors["2.3"] = {"value": vol, "status": st,
                      "evidence": {"monthly_net_flows": [round(x, 2) for x in nets], "sigma": round(sigma, 2) if sigma is not None else None,
                                   "monthly_income": income, "months": n_months}}

    # ---------------- 2.4 Savings buffer ----------------
    balance = float(t_bal[-1]) if len(t_bal) and not np.isnan(t_bal[-1]) else None
    if balance is None:
        days, st = None, "insufficient"
    elif income is None:
        days, st = None, "missing"
    else:
        if balance < 0:
            _flag(flags, "NEGATIVE_BALANCE", "2.4")
        days, st = (math.floor(max(balance, 0.0) / (income / 30.0)), "ok")
    factors["2.4"] = {"value": days, "status": st,
                      "evidence": {"liquid_balance": round(balance, 2) if balance is not None else None, "monthly_income": income}}

    # ---------------- 3.1 On-time payment rate ----------------
    w12b = add_months(as_of, -P.WINDOWS["on_time_months"])
    b12 = o_due >= w12b
    n_bills = int(b12.sum())
    n_ontime = int(o_ontime[b12].sum())
    by_type = {t: {"due": int((b12 & (o_type == t)).sum()), "on_time": int((b12 & (o_type == t) & o_ontime).sum())}
               for t in P.BILL_TYPES if (b12 & (o_type == t)).any()}
    if "utility" not in by_type:
        _flag(flags, "UTILITY_HISTORY_MISSING", "3.1")
    if n_bills < P.MIN_BILLS_FOR_ON_TIME:
        rate, st = None, "insufficient"
        _flag(flags, "BILLS_INSUFFICIENT", "3.1")
    else:
        rate, st = n_ontime / n_bills, "ok"
    factors["3.1"] = {"value": rate, "status": st,
                      "evidence": {"bills_due": n_bills, "bills_on_time": n_ontime, "by_type": by_type,
                                   "autopay_share": round(float(ob["autopay"][omask][b12].mean()), 3) if n_bills else 0.0}}

    # ---------------- 3.2 Debt-to-income ----------------
    n3 = P.WINDOWS["dti_complete_months"]
    d_start = (as_of_m - n3).astype("datetime64[D]")
    debt_sel = np.isin(o_type, list(P.DEBT_BILL_TYPES)) & (o_due >= d_start)
    monthly_debt = float(o_amt[debt_sel].sum()) / n3
    if income is None:
        dti, st = None, "missing"
    else:
        dti, st = monthly_debt / income, "ok"
    factors["3.2"] = {"value": dti, "status": st,
                      "evidence": {"monthly_debt_due": round(monthly_debt, 2), "monthly_income": income}}

    # ---------------- 3.3 Credit utilization ----------------
    lines = [a for a in user.accounts if a["account_type"] in P.REVOLVING_ACCOUNT_TYPES
             and not np.isnat(a["open"]) and a["open"] < as_of and (np.isnat(a["close"]) or a["close"] > as_of)]
    st_ = user.stmt
    smask = st_["date"] < as_of
    tot_bal, tot_lim, verified, per_line = 0.0, 0.0, 0, []
    for a in lines:
        sel = smask & (st_["account"] == a["account_id"])
        if sel.any():
            i = np.flatnonzero(sel)[-1]
            tot_bal += float(st_["outstanding"][i])
            tot_lim += float(st_["limit"][i])
            verified += 1
            per_line.append({"account_id": a["account_id"], "type": a["account_type"], "limit": float(st_["limit"][i]),
                             "outstanding": float(st_["outstanding"][i]), "statement": str(st_["date"][i])})
        else:
            per_line.append({"account_id": a["account_id"], "type": a["account_type"], "limit": a["limit"], "outstanding": None})
    if not lines:
        util, line_state, st = None, "NO_LINE", "na"
        _flag(flags, "NO_CREDIT_LINE", "3.3")
    elif verified == 0 or tot_lim <= 0:
        util, line_state, st = None, "LINE_UNVERIFIED", "unverified"
        _flag(flags, "UTILIZATION_UNVERIFIED", "3.3")
    else:
        util, st = tot_bal / tot_lim, "ok"
        line_state = "LINE_LOW" if util <= 0.30 else ("LINE_MID" if util <= 0.50 else "LINE_HIGH")
        if util > 1:
            _flag(flags, "OVERLIMIT", "3.3")
    factors["3.3"] = {"value": util, "status": st,
                      "evidence": {"line_state": line_state, "open_lines": len(lines), "verified_lines": verified,
                                   "total_outstanding": round(tot_bal, 2), "total_limit": round(tot_lim, 2), "lines": per_line}}

    # ---------------- 3.4 Recent delinquency severity ----------------
    w24 = add_months(as_of, -P.WINDOWS["delinquency_months"])
    b24 = o_due >= w24
    dpd = _dpd_as_of(o_due[b24], o_paid[b24], as_of)
    ev = dpd >= P.DELINQUENCY_EVENT_DPD
    ev_types, ev_due, ev_dpd = o_type[b24][ev], o_due[b24][ev], dpd[ev]
    if P.DELINQUENCY_COUNT_MODE == "per_month":
        n_events = len(np.unique(ev_due.astype("datetime64[M]")))
    else:
        n_events = int(ev.sum())
    worst = int(ev_dpd.max()) if len(ev_dpd) else 0
    events = [{"type": str(t), "due_date": str(d), "dpd": int(x), "bucket": "90+" if x >= 90 else ("60-89" if x >= 60 else "30-59"),
               "rolls_off": str(add_months(d, P.WINDOWS["delinquency_months"]))}
              for t, d, x in zip(ev_types, ev_due, ev_dpd)]
    st = "ok"
    if b24.sum() == 0:
        st = "thin"
        _flag(flags, "THIN_REPAYMENT_HISTORY", "3.4")
    factors["3.4"] = {"value": n_events, "status": st,
                      "evidence": {"events": n_events, "worst_dpd": worst, "bills_24m": int(b24.sum()),
                                   "late_under_30": int(((dpd > 0) & (dpd < 30)).sum()), "event_list": events[-10:]}}

    # ---------------- 4.1 Positive habits ----------------
    h_start = as_of_m - 12
    in12 = (t_month >= h_start) & ~t_credit
    sav = in12 & (t_cat == "Savings")
    micro_months = set(t_mi[sav & (t_sub != "recurring_investment")].tolist())
    rec_months = sorted(set(t_mi[sav & (t_sub == "recurring_investment")].tolist()))
    charity_months = set(t_mi[in12 & (t_cat == "Charity")].tolist())
    best_run, run, prev = 0, 0, None
    for m in rec_months:
        run = run + 1 if prev is not None and m == prev + 1 else 1
        best_run, prev = max(best_run, run), m
    habits = []
    if len(micro_months) >= P.HABIT_RULES["PH-01"]["months_required"]:
        habits.append({"id": "PH-01", "name": P.HABIT_RULES["PH-01"]["name"], "evidence": f"savings deposits in {len(micro_months)} of the last 12 months"})
    if len(charity_months) >= P.HABIT_RULES["PH-02"]["months_required"]:
        habits.append({"id": "PH-02", "name": P.HABIT_RULES["PH-02"]["name"], "evidence": f"charitable giving in {len(charity_months)} of the last 12 months"})
    if best_run >= P.HABIT_RULES["PH-03"]["consecutive_months"]:
        habits.append({"id": "PH-03", "name": P.HABIT_RULES["PH-03"]["name"], "evidence": f"recurring investment for {best_run} consecutive months"})
    factors["4.1"] = {"value": len(habits), "status": "ok",
                      "evidence": {"habits": habits, "micro_savings_months": len(micro_months),
                                   "charity_months": len(charity_months), "recurring_run": best_run}}

    # ---------------- 4.2 Risk flags ----------------
    lf = user.life
    lm = lf["date"] < as_of
    addr = lm & (lf["type"] == "address_change") & (lf["date"] >= add_months(as_of, -P.FLAG_RULES["RF-01"]["window_months"]))
    inq = lm & (lf["type"] == "credit_inquiry") & (lf["date"] >= add_months(as_of, -P.FLAG_RULES["RF-02"]["window_months"]))
    risk = []
    if addr.sum() >= P.FLAG_RULES["RF-01"]["min_events"]:
        last = lf["date"][addr].max()
        risk.append({"id": "RF-01", "name": P.FLAG_RULES["RF-01"]["name"], "evidence": f"address changed {str(last)}",
                     "expires": str(add_months(last, 12))})
    if inq.sum() >= P.FLAG_RULES["RF-02"]["min_events"]:
        dates = np.sort(lf["date"][inq])
        risk.append({"id": "RF-02", "name": P.FLAG_RULES["RF-02"]["name"], "evidence": f"{int(inq.sum())} credit inquiries in the last 6 months",
                     "expires": str(add_months(dates[-2], 6))})
    factors["4.2"] = {"value": len(risk), "status": "ok",
                      "evidence": {"flags": risk, "address_changes_12m": int(addr.sum()), "inquiries_6m": int(inq.sum())}}

    # ---------------- identity gate (MD-12) ----------------
    if user.match_confidence is not None and user.match_confidence < P.NO_SCORE_ID_THRESHOLD:
        _flag(flags, "ID_UNVERIFIED")
    elif user.match_confidence is not None and user.match_confidence < P.WEAK_ID_THRESHOLD:
        _flag(flags, "WEAK_ID")

    # ---------------- extra ML-only values (never used by rules) ----------------
    late_12m = int(n_bills - n_ontime) if n_bills else 0
    all_months = len(np.unique(t_month))
    ml_values = {
        "income": income, "income_source": income_source, "income_cv": income_cv,
        "lifestyle_share": (lifestyle / consumption) if consumption > 0 else None,
        "avg_monthly_spend": avg_spend, "late_bills_12m": late_12m, "txn_months": all_months,
        "age": user.age, "city_tier": user.city_tier, "employment_type": emp_type,
        "housing_status": housing, "open_lines": len(lines), "has_loan": any(a["account_type"] == "loan" for a in user.accounts
                                                                          if not np.isnat(a["open"]) and a["open"] < as_of),
    }

    return {"as_of": str(as_of), "factors": factors, "flags": flags, "income": {
        "value": income, "source": income_source, "declared": declared, "verified": round(verified_income, 2)},
        "ml_values": ml_values}
