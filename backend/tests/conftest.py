"""Shared test helpers: hand-built synthetic applicants.

Each builder writes raw records directly (no generator, no dataset), so the
expected points in the ground-truth tests are worked out by hand from these
records and the official scoring table, independently of the feature code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features.userdata import NAT, UserData  # noqa: E402

AS_OF = np.datetime64("2026-06-01", "D")
# 13 complete months before the as-of date: 2025-05 .. 2026-05
MONTHS = [np.datetime64("2025-05", "M") + i for i in range(13)]


def day(month: np.datetime64, d: int) -> np.datetime64:
    return month.astype("datetime64[D]") + (d - 1)


class Builder:
    def __init__(self, user_id="T_USER", **demo):
        self.ud = UserData(user_id=user_id, **demo)
        self.t: list[tuple] = []
        self.o: list[tuple] = []
        self.s: list[tuple] = []
        self.l: list[tuple] = []

    def txn(self, date, amount, category, credit=False, subtype="", balance=np.nan):
        self.t.append((date, float(amount), category, credit, float(balance), subtype))
        return self

    def bill(self, typ, due, lag_days=0, amount=1000.0, autopay=False, account=""):
        paid = NAT if lag_days is None else due + int(lag_days)
        self.o.append((typ, due, paid, float(amount), autopay, account))
        return self

    def stmt(self, account, date, limit, outstanding):
        self.s.append((account, date, float(limit), float(outstanding), round(outstanding * 0.05, 2)))
        return self

    def life(self, typ, date):
        self.l.append((typ, date))
        return self

    def build(self) -> UserData:
        u = self.ud
        if self.t:
            c = list(zip(*self.t))
            u.append_txn({"date": np.array(c[0], "datetime64[D]"), "amount": c[1], "category": c[2], "is_credit": c[3],
                          "balance": c[4], "subtype": c[5], "hyp": [False] * len(self.t)})
        if self.o:
            c = list(zip(*self.o))
            u.append_obl({"type": c[0], "due": np.array(c[1], "datetime64[D]"), "paid": np.array(c[2], "datetime64[D]"),
                          "amount_due": c[3], "autopay": c[4], "account": c[5], "hyp": [False] * len(self.o)})
        if self.s:
            c = list(zip(*self.s))
            u.append_stmt({"account": c[0], "date": np.array(c[1], "datetime64[D]"), "limit": c[2], "outstanding": c[3],
                           "min_due": c[4], "hyp": [False] * len(self.s)})
        if self.l:
            c = list(zip(*self.l))
            u.append_life({"type": c[0], "date": np.array(c[1], "datetime64[D]"), "hyp": [False] * len(self.l)})
        return u.sort()


def strong_applicant() -> UserData:
    """Salaried 40 months, owns home, every bill on time, 27% spend, savings habit, no credit line."""
    b = Builder("T_STRONG", age=34, education_level="Master", employment_status="salaried", monthly_income=50000.0,
                city_tier=1, housing_status="own")
    b.ud.employment.append({"employment_type": "salaried", "start": np.datetime64("2023-01-15"), "end": NAT, "declared_income": 50000.0, "hyp": False})
    b.ud.residence.append({"housing_status": "own", "start": np.datetime64("2019-03-01"), "end": NAT, "monthly_rent": None, "city_tier": 1})
    for m in MONTHS:
        b.txn(day(m, 1), 50000, "Salary", credit=True)
        b.txn(day(m, 5), 500, "Telecom")
        b.txn(day(m, 6), 2000, "Utility Bill")
        b.txn(day(m, 10), 8000, "Food")
        b.txn(day(m, 14), 1500, "Dining")
        b.txn(day(m, 20), 1500, "Shopping")
        b.txn(day(m, 25), 1000, "Savings", subtype="micro_savings")
        b.bill("telecom", day(m, 5), 0, 500)
        b.bill("utility", day(m, 6), 0, 2000)
    b.txn(day(MONTHS[-1], 28), 100, "Transport", balance=400000)   # last balance: Rs 4,00,000
    return b.build()


def weak_applicant() -> UserData:
    """Gig worker 6 months, renter with a late rent bill, two 30+ day delinquencies, 75% card utilisation, 2 risk flags."""
    b = Builder("T_WEAK", age=27, education_level="High School", employment_status="gig", monthly_income=20000.0,
                city_tier=2, housing_status="rent")
    b.ud.employment.append({"employment_type": "gig", "start": np.datetime64("2025-11-10"), "end": NAT, "declared_income": 20000.0, "hyp": False})
    b.ud.residence.append({"housing_status": "rent", "start": np.datetime64("2024-01-01"), "end": NAT, "monthly_rent": 7000.0, "city_tier": 2})
    b.ud.accounts.append({"account_id": "CARD1", "account_type": "card", "limit": 20000.0, "emi": 0.0,
                          "open": np.datetime64("2024-06-01"), "close": NAT, "hyp": False})
    b.ud.accounts.append({"account_id": "LOAN1", "account_type": "loan", "limit": 100000.0, "emi": 6000.0,
                          "open": np.datetime64("2024-06-01"), "close": NAT, "hyp": False})
    late_telecom = {np.datetime64("2025-07", "M"), np.datetime64("2025-11", "M"), np.datetime64("2026-04", "M")}
    for i, m in enumerate(MONTHS):
        b.txn(day(m, 1), 20000, "Gig Payout", credit=True)
        b.txn(day(m, 3), 7000, "Rent")
        b.txn(day(m, 5), 400, "Telecom")
        b.txn(day(m, 6), 1000, "Utility Bill")
        b.txn(day(m, 10), 5000, "Food")
        b.txn(day(m, 14), 3000, "Dining")
        b.txn(day(m, 20), 6000 if i % 2 else 0.01, "Shopping")   # alternating months (0.01 keeps the row positive)
        b.bill("rent", day(m, 3), 40 if m == np.datetime64("2026-02", "M") else 0, 7000)
        b.bill("telecom", day(m, 5), 5 if m in late_telecom else 0, 400)
        b.bill("utility", day(m, 6), 70 if m == np.datetime64("2025-10", "M") else 0, 1000)
        b.bill("emi", day(m, 7), 0, 6000, account="LOAN1")
        b.stmt("CARD1", day(m, 20), 20000, 15000)
    b.txn(day(MONTHS[-1], 28), 100, "Transport", balance=15000)
    b.life("address_change", np.datetime64("2025-09-01"))
    b.life("credit_inquiry", np.datetime64("2026-01-15"))
    b.life("credit_inquiry", np.datetime64("2026-03-15"))
    return b.build()


def missing_data_applicant() -> UserData:
    """No employment, no education, no income, no housing, two months of transactions, no bills."""
    b = Builder("T_MISSING", age=None, education_level=None, employment_status=None, monthly_income=None,
                city_tier=None, housing_status=None)
    for m in MONTHS[-2:]:
        b.txn(day(m, 10), 3000, "Food")
        b.txn(day(m, 15), 1000, "Shopping")
    return b.build()


@pytest.fixture
def strong():
    return strong_applicant()


@pytest.fixture
def weak():
    return weak_applicant()


@pytest.fixture
def missing():
    return missing_data_applicant()
