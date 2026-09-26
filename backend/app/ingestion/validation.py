"""Schema and data-quality validation for ingested files (rules DQ-01..DQ-11).

``validate(table, df, known_users)`` never mutates its input. It returns a
cleaned copy plus a list of issue records, each with a check code, severity,
count and a few sample row references. Rows are dropped only when they cannot
be used at all (unparseable date, non-positive amount, unknown user,
duplicate primary key); everything else is kept and reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.rules import policy as P

KNOWN_CATEGORIES = P.CONSUMPTION_CATEGORIES | P.ESSENTIAL_CATEGORIES | P.INCOME_CATEGORIES | {"Savings", "Card Payment", "Loan EMI"}


@dataclass
class TableSpec:
    required: tuple
    optional: tuple = ()
    key: str | None = None
    dates: tuple = ()
    nullable_dates: tuple = ()
    numeric: tuple = ()
    enums: dict = field(default_factory=dict)
    user_fk: bool = True


SPECS = {
    "demographics": TableSpec(("user_id", "age", "education_level", "employment_status", "monthly_income", "city_tier"),
                              ("applicant_id", "housing_status", "cohort", "employment_type"), key="user_id",
                              numeric=("age", "monthly_income", "city_tier"), user_fk=False),
    "transactions": TableSpec(("transaction_id", "user_id", "date", "amount", "category", "type"),
                              ("status", "balance_after", "subtype", "applicant_id"), key="transaction_id",
                              dates=("date",), numeric=("amount",), enums={"type": {"DEBIT", "CREDIT"}}),
    "obligations": TableSpec(("bill_id", "user_id", "obligation_type", "due_date", "amount_due", "paid_date", "days_past_due", "status"),
                             ("amount_paid", "autopay", "credit_account_id"), key="bill_id", dates=("due_date",),
                             nullable_dates=("paid_date",), numeric=("amount_due",),
                             enums={"obligation_type": set(P.BILL_TYPES), "status": {"Completed", "Late", "Missed"}}),
    "employment_spells": TableSpec(("spell_id", "user_id", "employment_type", "start_date"), ("employer_category", "end_date", "declared_income"),
                                   key="spell_id", dates=("start_date",), nullable_dates=("end_date",)),
    "residence_spells": TableSpec(("spell_id", "user_id", "housing_status", "start_date"), ("city_tier", "monthly_rent", "end_date"),
                                  key="spell_id", dates=("start_date",), nullable_dates=("end_date",),
                                  enums={"housing_status": {"own", "rent", "family", "none"}}),
    "credit_accounts": TableSpec(("credit_account_id", "user_id", "account_type", "limit_or_principal", "open_date"),
                                 ("lender_type", "emi", "close_date"), key="credit_account_id", dates=("open_date",),
                                 nullable_dates=("close_date",), numeric=("limit_or_principal",),
                                 enums={"account_type": {"card", "loan", "bnpl"}}),
    "card_statements": TableSpec(("account_id", "user_id", "statement_month", "credit_limit", "outstanding_balance", "minimum_due"),
                                 ("applicant_id", "opening_balance", "card_spend", "payment_amount", "payment_status", "utilization"),
                                 numeric=("credit_limit", "outstanding_balance", "minimum_due")),
    "life_events": TableSpec(("event_id", "user_id", "event_type", "event_date"), (), key="event_id", dates=("event_date",),
                             enums={"event_type": {"credit_inquiry", "address_change"}}),
    "product_catalog": TableSpec(("product_id", "product_name", "min_score", "type", "interest_rate"), (), key="product_id",
                                 numeric=("min_score",), user_fk=False),
}


def _issue(issues, table, code, severity, mask_or_count, df=None, message="", id_col=None):
    count = int(mask_or_count.sum()) if hasattr(mask_or_count, "sum") else int(mask_or_count)
    if count == 0:
        return
    sample = []
    if df is not None and hasattr(mask_or_count, "sum"):
        col = id_col if id_col and id_col in df else None
        sample = (df.loc[mask_or_count, col].astype(str).head(5).tolist() if col
                  else [str(i) for i in df.index[mask_or_count][:5]])
    issues.append({"file": table, "check_code": code, "severity": severity, "count": count,
                   "row_ref": ",".join(sample), "message": message})


def validate(table: str, df: pd.DataFrame, known_users: set | None = None) -> tuple[pd.DataFrame, list]:
    spec = SPECS[table]
    issues: list = []
    missing = [c for c in spec.required if c not in df.columns]
    if missing:
        issues.append({"file": table, "check_code": "SCHEMA_MISSING_COLUMNS", "severity": "error", "count": len(missing),
                       "row_ref": "", "message": f"missing required columns: {missing}"})
        return df.iloc[0:0].copy(), issues
    out = df.copy()
    id_col = spec.key or "user_id"
    drop = pd.Series(False, index=out.index)

    for c in spec.dates:
        parsed = pd.to_datetime(out[c], errors="coerce", format="mixed")
        bad = parsed.isna() | (parsed < pd.Timestamp("2000-01-01"))
        _issue(issues, table, "DQ-02_INVALID_DATE", "error", bad, out, f"{c} unparseable or before 2000; row dropped", id_col)
        drop |= bad
        out[c] = parsed.dt.strftime("%Y-%m-%d")
        future = parsed > pd.Timestamp(P.DATA_CUTOFF)
        _issue(issues, table, "DQ-06_AFTER_CUTOFF", "info", future & ~bad, out,
               f"{c} after the {P.DATA_CUTOFF} data cutoff; kept, excluded from scoring by the as-of date", id_col)
    for c in spec.nullable_dates:
        if c in out:
            raw_present = out[c].notna() & (out[c].astype(str).str.strip() != "")
            parsed = pd.to_datetime(out[c], errors="coerce", format="mixed")
            bad = raw_present & parsed.isna()
            _issue(issues, table, "DQ-02_INVALID_DATE", "warning", bad, out, f"{c} unparseable; treated as missing", id_col)
            out[c] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), None)
    for c in spec.numeric:
        num = pd.to_numeric(out[c], errors="coerce")
        nonnum = out[c].notna() & num.isna()
        _issue(issues, table, "DQ-01_NON_NUMERIC", "error" if c in spec.required and c != "monthly_income" else "warning",
               nonnum, out, f"{c} is not numeric", id_col)
        out[c] = num
    if table == "transactions":
        bad_amt = out["amount"].isna() | (out["amount"] <= 0)
        _issue(issues, table, "DQ-01_NON_POSITIVE_AMOUNT", "error", bad_amt, out, "amount missing or <= 0; row dropped", id_col)
        drop |= bad_amt
        out["type"] = out["type"].astype(str).str.upper().str.strip()
        unknown = ~out["category"].isin(KNOWN_CATEGORIES)
        _issue(issues, table, "DQ-01_UNKNOWN_CATEGORY", "warning", unknown, out,
               "category not in the known list; kept but ignored by category-based features", id_col)
        content_dup = out.duplicated(["user_id", "date", "amount", "category", "type"], keep="first")
        _issue(issues, table, "DQ-03_SAME_CONTENT", "info", content_dup, out,
               "same user/date/amount/category/type with a different transaction_id; kept (distinct bank records)", id_col)
        if "balance_after" in out:
            neg = pd.to_numeric(out["balance_after"], errors="coerce") < 0
            _issue(issues, table, "DQ-07_NEGATIVE_BALANCE", "info", neg, out, "balance_after below zero; savings factor uses 0 days", id_col)
    if table == "demographics":
        bad_age = out["age"].notna() & ((out["age"] < 16) | (out["age"] > 100))
        _issue(issues, table, "DQ-01_IMPLAUSIBLE_AGE", "warning", bad_age, out, "age outside 16-100", id_col)
        neg_inc = out["monthly_income"].notna() & (out["monthly_income"] <= 0)
        _issue(issues, table, "DQ-08_NON_POSITIVE_INCOME", "warning", neg_inc, out, "monthly_income <= 0; treated as missing", id_col)
        out.loc[neg_inc, "monthly_income"] = np.nan
        _issue(issues, table, "MD-01_INCOME_MISSING", "info", out["monthly_income"].isna(), out,
               "monthly_income missing; income will be verified from transactions", id_col)
    if table == "obligations":
        dpd = pd.to_numeric(out["days_past_due"], errors="coerce")
        sentinel = dpd == 999
        _issue(issues, table, "DL-06_MISSED_SENTINEL", "info", sentinel, out, "days_past_due=999 (never paid); dpd recomputed from dates", id_col)
        bad_dpd = (dpd < 0) | ((out["status"] == "Completed") & (dpd > 3))
        _issue(issues, table, "DQ-10_IMPOSSIBLE_DPD", "warning", bad_dpd, out, "impossible days_past_due; recomputed from dates", id_col)
    for c, allowed in spec.enums.items():
        if c in out:
            bad = out[c].notna() & ~out[c].isin(allowed)
            sev = "error" if c in ("obligation_type", "type") else "warning"
            _issue(issues, table, "DQ-01_INVALID_ENUM", sev, bad, out, f"{c} not in {sorted(allowed)}", id_col)
            if sev == "error":
                drop |= bad
    if spec.key and spec.key in out:
        dup = out.duplicated(spec.key, keep="first")
        _issue(issues, table, "DQ-03_DUPLICATE_KEY", "error", dup, out, f"duplicate {spec.key}; later copies dropped", id_col)
        drop |= dup
    if spec.user_fk and known_users is not None:
        orphan = ~out["user_id"].isin(known_users)
        _issue(issues, table, "DQ-05_UNKNOWN_USER", "error", orphan, out, "user_id not in demographics; row dropped", id_col)
        drop |= orphan
    return out.loc[~drop].copy(), issues


def check_id_mapping(demo: pd.DataFrame, idmap: pd.DataFrame, txn_sample: pd.DataFrame | None = None) -> list:
    """DQ-04 duplicate applicants, DQ-05 inconsistent IDs, MD-12 weak matches."""
    issues = []
    dup_app = idmap.duplicated("applicant_id", keep=False)
    _issue(issues, "id_mapping", "DQ-04_DUPLICATE_APPLICANT", "error", dup_app, idmap, "applicant_id mapped to several user_ids", "user_id")
    merged = demo[["user_id", "applicant_id"]].merge(idmap, on="user_id", how="left", suffixes=("", "_map"))
    mism = merged["applicant_id_map"].notna() & (merged["applicant_id"] != merged["applicant_id_map"])
    _issue(issues, "id_mapping", "DQ-05_ID_MISMATCH", "warning", mism, merged, "demographics applicant_id differs from id_mapping", "user_id")
    weak = idmap["match_confidence"] < P.WEAK_ID_THRESHOLD
    _issue(issues, "id_mapping", "MD-12_WEAK_ID", "warning", weak, idmap, "match_confidence < 0.8; offers withheld", "user_id")
    if txn_sample is not None and "applicant_id" in txn_sample:
        m = txn_sample[["user_id", "applicant_id"]].drop_duplicates().merge(idmap, on="user_id", how="left", suffixes=("", "_map"))
        bad = m["applicant_id_map"].notna() & (m["applicant_id"] != m["applicant_id_map"])
        _issue(issues, "transactions", "DQ-05_ID_MISMATCH", "warning", bad, m, "transaction applicant_id differs from id_mapping", "user_id")
    return issues
