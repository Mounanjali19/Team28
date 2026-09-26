"""Central rule policy for the AltCredit rule-based credit engine.

Every threshold, band, window, tier edge and open-decision default used by the
rule engine lives here and nowhere else. The frontend never re-implements any
of these values; it reads them from the API (`GET /api/policy`).

Sources
-------
* OFFICIAL  - the AltCredit 2026 use-case PDF, scoring table pp.2-3.
* DERIVED   - implementation detail the official rule needs (rulebook v0.1).
* PROPOSED  - rulebook v0.1 default for something the PDF leaves open.

Open decisions D1-D7 from rulebook v0.1 are still unanswered; the defaults
below are the rulebook's stated defaults and can be flipped here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

RULE_VERSION = "altcredit-rules-1.0.0 (rulebook v0.1 defaults)"

# --------------------------------------------------------------------------
# Open decisions (rulebook v0.1, awaiting product-owner confirmation)
# --------------------------------------------------------------------------
OPEN_DECISIONS = {
    "D1_grace_days": 0,               # 3.1/1.2/1.3 'on or before due date': strict dpd == 0
    "D2_delinquency_count_mode": "per_bill",   # 3.4 multiple misses counted per late bill
    "D3_renter_12m_with_late_rent_points": 30,  # renter >=12 mo whose rent streak is broken
    "D4_habits": "PH-01 micro-savings 9/12 months, PH-02 charity 4/12 months, PH-03 recurring investment 6 consecutive months",
    "D5_flags": "RF-01 address change <=12 mo, RF-02 >=2 credit inquiries <=6 mo; -20 per flag type",
    "D6_tiers": "5 tiers with edges at catalog minimums 350/550/650/750",
    "D7_ml_bands": "ML PD bands 5% / 12% / 25%",
}

GRACE_DAYS = OPEN_DECISIONS["D1_grace_days"]
DELINQUENCY_COUNT_MODE = OPEN_DECISIONS["D2_delinquency_count_mode"]  # "per_bill" | "per_month"

# --------------------------------------------------------------------------
# Scoring bands (OFFICIAL points; comparison operators DERIVED, rule SC-07)
# A band table is an ordered list of (threshold, points); first match wins.
#   "ge" tables: value >= threshold  (higher is better)
#   "le" tables: value <= threshold  (lower is better)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BandTable:
    op: str                     # "ge" or "le"
    bands: tuple                # ((threshold, points, label), ...)
    else_points: int
    else_label: str

    def evaluate(self, value: float) -> tuple[int, str]:
        for threshold, points, label in self.bands:
            if (self.op == "ge" and value >= threshold) or (self.op == "le" and value <= threshold):
                return points, label
        return self.else_points, self.else_label

    @property
    def max_points(self) -> int:
        return max([p for _, p, _ in self.bands] + [self.else_points])


BANDS = {
    "1.1": BandTable("ge", ((24, 150, "24+ months"), (12, 100, "12-23 months"), (6, 50, "6-11 months")), 0, "under 6 months"),
    "1.3": BandTable("ge", ((0.95, 70, ">=95% of months on time"), (0.80, 45, "80-94%"), (0.60, 20, "60-79%")), 0, "under 60%"),
    "2.1": BandTable("le", ((0.30, 120, "<=30% of income"), (0.50, 80, "30-50%"), (0.70, 40, "50-70%")), 0, "over 70%"),
    "2.2": BandTable("ge", ((0.70, 80, "essentials >=70%"), (0.55, 45, "55-69%"), (0.40, 20, "40-54%")), 0, "under 40%"),
    "2.3": BandTable("le", ((0.05, 70, "sigma <=5% of income"), (0.10, 40, "5-10%"), (0.20, 15, "10-20%")), 0, "over 20%"),
    "2.4": BandTable("ge", ((180, 80, "180+ days"), (90, 50, "90-179 days"), (30, 20, "30-89 days")), 0, "under 30 days"),
    "3.1": BandTable("ge", ((0.98, 200, ">=98% on time"), (0.95, 150, "95-97%"), (0.90, 100, "90-94%"), (0.80, 50, "80-89%")), 0, "under 80%"),
    "3.2": BandTable("le", ((0.20, 120, "DTI <=20%"), (0.35, 80, "21-35%"), (0.50, 40, "36-50%")), 0, "over 50%"),
    "3.3": BandTable("le", ((0.10, 100, "utilization <=10%"), (0.30, 70, "11-30%"), (0.50, 30, "31-50%")), 0, "over 50%"),
}

HOUSING_POINTS = {           # 1.2 OFFICIAL, family/renter-with-late-bill = PROPOSED (D3)
    "own": 80,
    "rent_12m_on_time": 60,
    "rent_short": 30,
    "rent_12m_broken_streak": OPEN_DECISIONS["D3_renter_12m_with_late_rent_points"],
    "family": 30,
    "none": 0,
}
HOUSING_STREAK_MONTHS = 12

EDUCATION_POINTS = {         # 1.4 OFFICIAL; diploma_cert -> "professional cert" is DERIVED
    "phd": 50, "master": 50, "bachelor": 40, "diploma_cert": 30, "high_school": 20, "below_hs": 0,
}
# Legacy (official sample) spellings -> canonical
EDUCATION_ALIASES = {
    "phd": "phd", "ph.d": "phd", "doctorate": "phd",
    "master's": "master", "masters": "master", "master": "master", "mba": "master",
    "bachelor's": "bachelor", "bachelors": "bachelor", "bachelor": "bachelor", "graduate": "bachelor",
    "diploma": "diploma_cert", "diploma_cert": "diploma_cert", "certification": "diploma_cert", "professional cert": "diploma_cert",
    "high school": "high_school", "high_school": "high_school", "12th": "high_school",
    "below_hs": "below_hs", "below high school": "below_hs", "none": "below_hs",
}

DELINQUENCY_POINTS = {       # 3.4 OFFICIAL
    "none": 150, "one_30": 100, "one_60": 50, "one_90_or_multiple": 0,
}
DELINQUENCY_EVENT_DPD = 30   # DL-01/DL-02: an event is a bill with dpd >= 30

HABIT_POINTS_EACH = 20       # 4.1 OFFICIAL
HABIT_CAP = 50
FLAG_POINTS_EACH = -20       # 4.2 OFFICIAL
FLAG_CAP = -50

HABIT_RULES = {              # PROPOSED (D4)
    "PH-01": {"name": "Regular micro-savings", "months_required": 9, "window_months": 12},
    "PH-02": {"name": "Charitable giving", "months_required": 4, "window_months": 12},
    "PH-03": {"name": "Recurring investment (SIP/RD)", "consecutive_months": 6, "window_months": 12},
}
FLAG_RULES = {               # PROPOSED (D5)
    "RF-01": {"name": "Recent address change", "window_months": 12, "min_events": 1},
    "RF-02": {"name": "Frequent credit inquiries", "window_months": 6, "min_events": 2},
}

SCORE_MIN, SCORE_MAX = 0, 1000      # SC-05 clamp (approved decision: cap, not rescale)
NO_CREDIT_LINE_POINTS = 70          # 3.3 no line -> N/A, neutral 70 (approved project decision)
UNVERIFIED_LINE_POINTS = 70         # MD-07 line without statement -> provisional 70

# --------------------------------------------------------------------------
# Windows (T-04/T-05) and data-sufficiency gates (MD-xx)
# --------------------------------------------------------------------------
WINDOWS = {
    "digital_footprint_months": 12,
    "spend_complete_months": 6,       # 2.1, 2.2 (DERIVED)
    "volatility_complete_months": 6,  # 2.3 (OFFICIAL 6 months)
    "on_time_months": 12,             # 3.1 (OFFICIAL)
    "dti_complete_months": 3,         # 3.2 (DERIVED)
    "delinquency_months": 24,         # 3.4 (OFFICIAL)
    "income_verify_months": 6,
}
MIN_TELECOM_MONTHS = 6          # MD-05
MIN_BILLS_FOR_ON_TIME = 6       # MD-09 / 3.1
MIN_COMPLETE_TXN_MONTHS = 3     # MD-08 / MD-10
INCOME_CONFLICT_RATIO = 1.5     # MD-11
WEAK_ID_THRESHOLD = 0.8         # MD-12: score but no offers
NO_SCORE_ID_THRESHOLD = 0.6     # MD-12: do not score

# Employment types that count as a "current job" for 1.1 (PDF: months at current
# job or continuous gig-platform earnings). Students and unemployed earn 0.
EMPLOYMENT_TYPES_COUNTED = {"salaried", "self_employed", "freelancer", "gig"}
GIG_TYPES = {"gig", "freelancer"}   # tenure = min(spell months, consecutive months with income)

# Transaction categories
INCOME_CATEGORIES = {"Salary", "Business Income", "Gig Payout", "Stipend", "Other Income"}
CONSUMPTION_CATEGORIES = {       # 2.1 numerator (rulebook R-2.1)
    "Food", "Dining", "Shopping", "Transport", "Healthcare", "Education", "Rent",
    "Utility Bill", "Telecom", "Cash Withdrawal", "Charity",
}
ESSENTIAL_CATEGORIES = {         # 2.2 (approved project decision)
    "Food", "Rent", "Utility Bill", "Telecom", "Transport", "Healthcare", "Education", "Loan EMI",
}
DISCRETIONARY_CATEGORIES = {"Dining", "Shopping", "Charity"}   # 2.2 denominator extras
LIFESTYLE_CATEGORIES = {"Dining", "Shopping"}                   # what-if overspend target
BILL_TYPES = ("rent", "utility", "telecom", "emi", "card_min")
DEBT_BILL_TYPES = ("emi", "card_min")
REVOLVING_ACCOUNT_TYPES = {"card", "bnpl"}

# As-of convention (T-01): historical applicant -> application date (first of month);
# live applicant -> 1 Jun 2026: the v2 ledger for live applicants ends 31 May 2026, so
# June 1 is the first day after the last complete month (same convention as historical).
LIVE_AS_OF = date(2026, 6, 1)
DATA_CUTOFF = date(2026, 6, 30)

# --------------------------------------------------------------------------
# Risk tiers (TR-01, PROPOSED D6): edges reuse catalog minimum scores.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    code: str
    name: str
    min_score: int
    max_score: int
    color: str
    meaning: str


RISK_TIERS = (
    Tier("T1", "Very High Risk", 0, 349, "#B42318", "Below every product minimum"),
    Tier("T2", "High Risk", 350, 549, "#C4540A", "Entry-level products only"),
    Tier("T3", "Moderate Risk", 550, 649, "#A36A00", "Mass-market products"),
    Tier("T4", "Low Risk", 650, 749, "#3F7D3A", "Standard card and lifestyle products"),
    Tier("T5", "Very Low Risk", 750, 1000, "#1E6B45", "All products"),
)
POLICY_ELIGIBLE_TIERS = {"T4", "T5"}   # 'rule favourable' side of the agreement matrix (ML-04)

# --------------------------------------------------------------------------
# ML validation (secondary; never changes rule outputs, ML-07)
# --------------------------------------------------------------------------
ML_PD_BANDS = (      # PROPOSED (D7): (upper bound exclusive, band)
    (0.05, "Low"),
    (0.12, "Moderate"),
    (0.25, "Elevated"),
    (1.01, "High"),
)
ML_MIN_TXN_MONTHS = 6
ML_LOW_CONFIDENCE_FLAGS = {"INSUFFICIENT_HISTORY", "WEAK_ID", "INCOME_MISSING", "THIN_REPAYMENT_HISTORY"}

# --------------------------------------------------------------------------
# Lender portal
# --------------------------------------------------------------------------
LENDER_DEFAULT_MIN_SCORE = 650   # LP-02 'Credit Score - 650 to' (upper bound truncated -> 1000)
LENDER_DEFAULT_MAX_SCORE = 1000
OFFER_DEFAULT_EXPIRY_DAYS = 30

# --------------------------------------------------------------------------
# What-if / counterfactual
# --------------------------------------------------------------------------
SIMULATION = {
    "default_horizon_months": 3,
    "max_horizon_months": 12,
    "saving_boost_default_amount": 1000,
    "overspend_default_share": 0.75,
    "overspend_default_months": 2,
    "delinquency_utility_days": 45,
    "delinquency_rent_days": 15,
    "counterfactual_horizons": (1, 2, 3, 6, 9, 12),
    "counterfactual_max_spend_cut": 0.40,       # CF-03 cut discretionary <= 40%
    "counterfactual_max_saving_share": 0.60,    # CF-03 <= 60% of monthly surplus
}

FACTOR_NAMES = {
    "1.1": "Employment Stability", "1.2": "Housing Status", "1.3": "Digital Footprint",
    "1.4": "Education / Skill Level", "2.1": "Spend-to-Income Ratio", "2.2": "Expense Diversity",
    "2.3": "Cash-flow Volatility", "2.4": "Savings / Emergency Fund", "3.1": "On-time Payment Rate",
    "3.2": "Debt-to-Income Ratio", "3.3": "Credit Utilization", "3.4": "Recent Delinquency Severity",
    "4.1": "Positive Financial Behaviour", "4.2": "Risk Flags",
}
FACTOR_COMPONENT = {
    "1.1": "Lifestyle", "1.2": "Lifestyle", "1.3": "Lifestyle", "1.4": "Lifestyle",
    "2.1": "Spending Behaviour", "2.2": "Spending Behaviour", "2.3": "Spending Behaviour", "2.4": "Spending Behaviour",
    "3.1": "Repayment Discipline", "3.2": "Repayment Discipline", "3.3": "Repayment Discipline", "3.4": "Repayment Discipline",
    "4.1": "Bonus / Penalty", "4.2": "Bonus / Penalty",
}
FACTOR_MAX = {
    "1.1": 150, "1.2": 80, "1.3": 70, "1.4": 50, "2.1": 120, "2.2": 80, "2.3": 70, "2.4": 80,
    "3.1": 200, "3.2": 120, "3.3": 100, "3.4": 150, "4.1": 50, "4.2": 0,
}
FACTOR_MIN = {k: 0 for k in FACTOR_MAX} | {"4.2": -50}


def tier_for(score: int) -> Tier:
    for t in RISK_TIERS:
        if t.min_score <= score <= t.max_score:
            return t
    raise ValueError(f"score {score} outside 0-1000")


def ml_band_for(pd_value: float) -> str:
    for upper, band in ML_PD_BANDS:
        if pd_value < upper:
            return band
    return "High"


def policy_snapshot() -> dict:
    """Serializable view of the policy, served to the frontend and stored with every score."""
    return {
        "rule_version": RULE_VERSION,
        "open_decisions": OPEN_DECISIONS,
        "bands": {k: {"op": b.op, "bands": [list(x) for x in b.bands], "else": [b.else_points, b.else_label]}
                  for k, b in BANDS.items()},
        "housing_points": HOUSING_POINTS,
        "education_points": EDUCATION_POINTS,
        "delinquency_points": DELINQUENCY_POINTS,
        "habit_rules": HABIT_RULES, "flag_rules": FLAG_RULES,
        "tiers": [t.__dict__ for t in RISK_TIERS],
        "ml_pd_bands": [list(b) for b in ML_PD_BANDS],
        "lender_default_score_range": [LENDER_DEFAULT_MIN_SCORE, LENDER_DEFAULT_MAX_SCORE],
        "simulation": {k: (list(v) if isinstance(v, tuple) else v) for k, v in SIMULATION.items()},
        "factor_names": FACTOR_NAMES, "factor_component": FACTOR_COMPONENT, "factor_max": FACTOR_MAX,
    }
