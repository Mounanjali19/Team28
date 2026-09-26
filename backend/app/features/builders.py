"""Build ``UserData`` objects from column-oriented frames (pandas or SQLite rows).

The same builder is used for the batch path (whole dataset from CSV/SQLite at
seed time) and for single-applicant lookups from SQLite at request time, so the
scoring input is identical on both paths.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.userdata import UserData, d64, NAT


def _dates(series) -> np.ndarray:
    return pd.to_datetime(series, errors="coerce").values.astype("datetime64[D]")


def _group_slices(df: pd.DataFrame, key="user_id"):
    """Return {user_id: (start, stop)} for a frame sorted by key."""
    if df.empty:
        return {}
    keys = df[key].values
    change = np.flatnonzero(keys[1:] != keys[:-1]) + 1
    starts = np.concatenate([[0], change])
    stops = np.concatenate([change, [len(keys)]])
    return {keys[s]: (s, e) for s, e in zip(starts, stops)}


def prepare_frames(frames: dict) -> dict:
    """Convert raw frames to sorted numpy columns keyed by user for fast slicing."""
    out = {}
    t = frames["transactions"].sort_values(["user_id", "date"], kind="stable")
    out["txn"] = {
        "cols": {"date": _dates(t["date"]), "amount": t["amount"].astype(float).values,
                 "category": t["category"].astype(str).values.astype("<U16"),
                 "is_credit": (t["type"].astype(str).str.upper() == "CREDIT").values,
                 "balance": t["balance_after"].astype(float).values if "balance_after" in t else np.zeros(len(t)),
                 "subtype": t["subtype"].fillna("").astype(str).values.astype("<U24") if "subtype" in t else np.full(len(t), "", "<U24"),
                 "hyp": np.zeros(len(t), bool)},
        "slices": _group_slices(t)}
    o = frames["obligations"].sort_values(["user_id", "due_date"], kind="stable")
    out["obl"] = {
        "cols": {"type": o["obligation_type"].astype(str).values.astype("<U10"), "due": _dates(o["due_date"]),
                 "paid": _dates(o["paid_date"]), "amount_due": o["amount_due"].astype(float).values,
                 "autopay": o["autopay"].astype(str).str.lower().isin(["true", "1"]).values,
                 "account": o["credit_account_id"].fillna("").astype(str).values.astype("<U16"),
                 "hyp": np.zeros(len(o), bool)},
        "slices": _group_slices(o)}
    s = frames["card_statements"].copy()
    if not s.empty:
        s["stmt_date"] = (pd.to_datetime(s["statement_month"]) + pd.offsets.MonthEnd(0))
    s = s.sort_values(["user_id", "stmt_date"], kind="stable") if not s.empty else s
    out["stmt"] = {
        "cols": {"account": s["account_id"].astype(str).values.astype("<U16") if not s.empty else np.array([], "<U16"),
                 "date": s["stmt_date"].values.astype("datetime64[D]") if not s.empty else np.array([], "datetime64[D]"),
                 "limit": s["credit_limit"].astype(float).values if not s.empty else np.array([], float),
                 "outstanding": s["outstanding_balance"].astype(float).values if not s.empty else np.array([], float),
                 "min_due": s["minimum_due"].astype(float).values if not s.empty else np.array([], float),
                 "hyp": np.zeros(len(s), bool)},
        "slices": _group_slices(s)}
    lf = frames["life_events"].sort_values(["user_id", "event_date"], kind="stable")
    out["life"] = {"cols": {"type": lf["event_type"].astype(str).values.astype("<U16"), "date": _dates(lf["event_date"]),
                            "hyp": np.zeros(len(lf), bool)},
                   "slices": _group_slices(lf)}
    out["emp"] = {u: g for u, g in frames["employment_spells"].groupby("user_id")}
    out["res"] = {u: g for u, g in frames["residence_spells"].groupby("user_id")}
    out["acc"] = {u: g for u, g in frames["credit_accounts"].groupby("user_id")}
    out["demo"] = frames["demographics"].set_index("user_id", drop=False)
    out["idmap"] = frames["id_mapping"].set_index("user_id")["match_confidence"].to_dict() if "id_mapping" in frames else {}
    return out


def _slice(block, uid, empty):
    if uid not in block["slices"]:
        return empty
    s, e = block["slices"][uid]
    return {k: v[s:e] for k, v in block["cols"].items()}


def _nan_to_none(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def build_user(prep: dict, uid: str) -> UserData:
    d = prep["demo"].loc[uid]
    ud = UserData(
        user_id=uid, applicant_id=_nan_to_none(d.get("applicant_id")), age=int(d["age"]) if _nan_to_none(d.get("age")) is not None else None,
        education_level=_nan_to_none(d.get("education_level")), employment_status=_nan_to_none(d.get("employment_status")),
        monthly_income=float(d["monthly_income"]) if _nan_to_none(d.get("monthly_income")) is not None else None,
        city_tier=int(d["city_tier"]) if _nan_to_none(d.get("city_tier")) is not None else None,
        housing_status=_nan_to_none(d.get("housing_status")), cohort=_nan_to_none(d.get("cohort")) or "live",
        match_confidence=float(prep["idmap"].get(uid, 1.0)), source=_nan_to_none(d.get("source")) or "altcredit_v2",
    )
    for _, r in prep["emp"].get(uid, pd.DataFrame()).iterrows():
        ud.employment.append({"employment_type": r["employment_type"], "start": d64(r["start_date"]), "end": d64(_nan_to_none(r["end_date"])),
                              "declared_income": _nan_to_none(r.get("declared_income")), "hyp": False})
    for _, r in prep["res"].get(uid, pd.DataFrame()).iterrows():
        ud.residence.append({"housing_status": r["housing_status"], "start": d64(r["start_date"]), "end": d64(_nan_to_none(r["end_date"])),
                             "monthly_rent": _nan_to_none(r.get("monthly_rent")), "city_tier": _nan_to_none(r.get("city_tier"))})
    for _, r in prep["acc"].get(uid, pd.DataFrame()).iterrows():
        ud.accounts.append({"account_id": r["credit_account_id"], "account_type": r["account_type"],
                            "limit": float(r["limit_or_principal"]), "emi": float(r["emi"] or 0),
                            "open": d64(r["open_date"]), "close": d64(_nan_to_none(r["close_date"])), "hyp": False})
    ud.txn = _slice(prep["txn"], uid, UserData.empty_txn())
    ud.obl = _slice(prep["obl"], uid, UserData.empty_obl())
    ud.stmt = _slice(prep["stmt"], uid, UserData.empty_stmt())
    ud.life = _slice(prep["life"], uid, UserData.empty_life())
    return ud
