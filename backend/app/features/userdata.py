"""In-memory container for one applicant's raw records.

All dates are numpy ``datetime64[D]``; missing dates are ``NaT``. Arrays are
kept column-wise so the feature pipeline can run in a few milliseconds, which
matters because the What-If simulator and the counterfactual search re-run the
full engine many times on hypothetical overlays.

Hypothetical (simulated) rows carry ``hyp=True``. Historical rows are never
edited: the simulator only appends (rule WI-G1).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

import numpy as np

NAT = np.datetime64("NaT", "D")


def d64(value) -> np.datetime64:
    """Coerce a date/str/None into datetime64[D] (NaT for empty)."""
    if value is None or value == "" or (isinstance(value, float) and np.isnan(value)):
        return NAT
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[D]")
    if isinstance(value, date):
        return np.datetime64(value.isoformat(), "D")
    return np.datetime64(str(value)[:10], "D")


def month_start(d: np.datetime64) -> np.datetime64:
    return d.astype("datetime64[M]").astype("datetime64[D]")


def add_months(d: np.datetime64, n: int) -> np.datetime64:
    """Add calendar months, clamping the day to the target month's length."""
    m = d.astype("datetime64[M]")
    day = (d - m.astype("datetime64[D]")).astype(int)
    target = m + n
    last_day = ((target + 1).astype("datetime64[D]") - target.astype("datetime64[D]")).astype(int) - 1
    return target.astype("datetime64[D]") + min(day, last_day)


def full_months_between(start: np.datetime64, end: np.datetime64) -> int:
    """Full calendar months from start to end (rule T-04)."""
    if np.isnat(start) or np.isnat(end) or start > end:
        return 0
    sm, em = start.astype("datetime64[M]"), end.astype("datetime64[M]")
    months = int((em - sm).astype(int))
    sday = int((start - sm.astype("datetime64[D]")).astype(int))
    eday = int((end - em.astype("datetime64[D]")).astype(int))
    if sday > eday:
        months -= 1
    return max(months, 0)


def _arr(values, dtype):
    return np.asarray(values, dtype=dtype) if len(values) else np.array([], dtype=dtype)


@dataclass
class UserData:
    user_id: str
    applicant_id: str | None = None
    age: int | None = None
    education_level: str | None = None
    employment_status: str | None = None
    monthly_income: float | None = None
    city_tier: int | None = None
    housing_status: str | None = None
    cohort: str = "live"
    match_confidence: float = 1.0
    source: str = "altcredit_v2"
    # spells / accounts as small lists of dicts
    employment: list = field(default_factory=list)   # {employment_type, start, end, declared_income, hyp}
    residence: list = field(default_factory=list)    # {housing_status, start, end, monthly_rent, city_tier}
    accounts: list = field(default_factory=list)     # {account_id, account_type, limit, emi, open, close, hyp}
    # column arrays
    txn: dict = field(default_factory=dict)          # date, amount, category, is_credit, balance, subtype, hyp
    obl: dict = field(default_factory=dict)          # type, due, paid, amount_due, autopay, account, hyp
    stmt: dict = field(default_factory=dict)         # account, date, limit, outstanding, min_due, hyp
    life: dict = field(default_factory=dict)         # type, date, hyp

    @staticmethod
    def empty_txn():
        return {"date": _arr([], "datetime64[D]"), "amount": _arr([], float), "category": _arr([], "<U16"),
                "is_credit": _arr([], bool), "balance": _arr([], float), "subtype": _arr([], "<U24"),
                "hyp": _arr([], bool)}

    @staticmethod
    def empty_obl():
        return {"type": _arr([], "<U10"), "due": _arr([], "datetime64[D]"), "paid": _arr([], "datetime64[D]"),
                "amount_due": _arr([], float), "autopay": _arr([], bool), "account": _arr([], "<U16"),
                "hyp": _arr([], bool)}

    @staticmethod
    def empty_stmt():
        return {"account": _arr([], "<U16"), "date": _arr([], "datetime64[D]"), "limit": _arr([], float),
                "outstanding": _arr([], float), "min_due": _arr([], float), "hyp": _arr([], bool)}

    @staticmethod
    def empty_life():
        return {"type": _arr([], "<U16"), "date": _arr([], "datetime64[D]"), "hyp": _arr([], bool)}

    def __post_init__(self):
        self.txn = self.txn or self.empty_txn()
        self.obl = self.obl or self.empty_obl()
        self.stmt = self.stmt or self.empty_stmt()
        self.life = self.life or self.empty_life()

    def clone(self) -> "UserData":
        return copy.deepcopy(self)

    @staticmethod
    def _append(cols: dict, rows: dict) -> dict:
        return {k: np.concatenate([cols[k], np.asarray(rows[k], dtype=cols[k].dtype)]) for k in cols}

    def append_txn(self, rows: dict):
        self.txn = self._append(self.txn, rows)

    def append_obl(self, rows: dict):
        self.obl = self._append(self.obl, rows)

    def append_stmt(self, rows: dict):
        self.stmt = self._append(self.stmt, rows)

    def append_life(self, rows: dict):
        self.life = self._append(self.life, rows)

    def sort(self):
        """Stable sort every table by date so 'last balance' and streaks are well-defined."""
        o = np.argsort(self.txn["date"], kind="stable")
        self.txn = {k: v[o] for k, v in self.txn.items()}
        o = np.argsort(self.obl["due"], kind="stable")
        self.obl = {k: v[o] for k, v in self.obl.items()}
        o = np.argsort(self.stmt["date"], kind="stable")
        self.stmt = {k: v[o] for k, v in self.stmt.items()}
        o = np.argsort(self.life["date"], kind="stable")
        self.life = {k: v[o] for k, v in self.life.items()}
        return self

    def last_record_date(self) -> np.datetime64:
        dates = [x.max() for x in (self.txn["date"], self.obl["due"]) if len(x)]
        return max(dates) if dates else NAT
