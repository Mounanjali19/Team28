# Rule engine

Source: `backend/app/features/engineering.py` (measurement) and `backend/app/rules/engine.py` (points). Configuration: `backend/app/rules/policy.py`. Version string: `altcredit-rules-1.0.0 (rulebook v0.1 defaults)`.

## The 14 rules

| Rule | Measured value (window) | Points |
|---|---|---|
| 1.1 Employment stability | full months in current job; gig/freelance = min(spell months, consecutive income months) | ≥24: 150 · 12–23: 100 · 6–11: 50 · else 0 |
| 1.2 Housing | own; renter ≥12 mo with last 12 rent bills on time; renter <12 mo; family; none | 80 · 60 · 30 · 30 · 0 |
| 1.3 Digital footprint | share of months (last 12) in which every mobile/internet bill was on time; needs ≥6 months | ≥95%: 70 · 80–94%: 45 · 60–79%: 20 · else 0 |
| 1.4 Education | highest credential | Master/PhD 50 · Bachelor 40 · Diploma/cert 30 · High school 20 · below 0 |
| 2.1 Spend-to-income | avg monthly consumption spend / income (6 complete months, ≥3 needed) | ≤30%: 120 · ≤50%: 80 · ≤70%: 40 · else 0 |
| 2.2 Expense diversity | essentials / (essentials + dining + shopping + charity) | ≥70%: 80 · ≥55%: 45 · ≥40%: 20 · else 0 |
| 2.3 Cash-flow volatility | population std-dev of monthly net flow / income (6 months) | ≤5%: 70 · ≤10%: 40 · ≤20%: 15 · else 0 |
| 2.4 Savings buffer | floor(last balance / (income/30)) days | ≥180: 80 · ≥90: 50 · ≥30: 20 · else 0 |
| 3.1 On-time payments | bills paid on/before due ÷ bills due (rent, utility, telecom, EMI, card min; last 12 months; ≥6 bills) | ≥98%: 200 · ≥95%: 150 · ≥90%: 100 · ≥80%: 50 · else 0 |
| 3.2 Debt-to-income | EMI + card minimum due per month (last 3 months) / income | ≤20%: 120 · ≤35%: 80 · ≤50%: 40 · else 0 |
| 3.3 Credit utilisation | Σ latest statement balance / Σ limit over open revolving lines | ≤10%: 100 · ≤30%: 70 · ≤50%: 30 · else 0; no line: neutral 70 |
| 3.4 Delinquency severity | bills ≥30 days past due in the last 24 months | none 150 · one 30–59: 100 · one 60–89: 50 · one 90+ or several: 0 |
| 4.1 Positive habits | PH-01 savings 9/12 months · PH-02 charity 4/12 · PH-03 recurring investment 6 consecutive | +20 each, cap +50 |
| 4.2 Risk flags | RF-01 address change ≤12 mo · RF-02 ≥2 credit inquiries ≤6 mo | −20 each, floor −50 |

Maximum raw total is 1320. The score is clamped to 0–1000; the raw total is kept and shown when capped.

Band edges are inclusive as written (for example 2.1 at exactly 30% earns 120). `tests/test_rules.py` checks every edge value above.

## Tiers and decision

| Tier | Score | Meaning |
|---|---|---|
| T1 Very High Risk | 0–349 | below every product minimum |
| T2 High Risk | 350–549 | starter products |
| T3 Moderate Risk | 550–649 | mass-market |
| T4 Low Risk | 650–749 | most products |
| T5 Very Low Risk | 750–1000 | all products |

Tier edges sit at the catalog minimums (D6). A product is eligible when `policy score ≥ min_score` and the identity match is at least 0.6. Below 0.6 the applicant is still scored, but the decision is REFER and nothing is eligible. Between 0.6 and 0.8 (weak ID) the applicant is eligible, but lenders cannot push offers until identity is confirmed. Otherwise the decision is ACCEPT when at least one product is eligible and REJECT when none is. Bulk campaigns also skip applicants with POOR data quality.

## Missing data

Missing data never earns points and is never imputed for the rules. Each gap raises a flag (for example `INCOME_MISSING`, `INSUFFICIENT_HISTORY`, `TELECOM_INSUFFICIENT`, `NO_CREDIT_LINE`, `WEAK_ID`). Data quality is GOOD when all 12 measurable rules are measured and no warning flag is raised, LIMITED when coverage is below 100% or there is a warning, and POOR when coverage is below 75% or a flag is critical. Two neutral cases are deliberate project decisions: no credit line scores 70 on 3.3, and no bills in 24 months scores 150 on 3.4 but raises `THIN_REPAYMENT_HISTORY`.

## Open decisions (defaults applied, change in `policy.py`)

| Id | Default |
|---|---|
| D1 grace days on bills | 0 (paid on or before the due date) |
| D2 counting multiple late bills | per bill |
| D3 renter ≥12 mo with a late rent bill | 30 |
| D4 habit definitions | PH-01 9/12, PH-02 4/12, PH-03 6 consecutive |
| D5 risk flag definitions | RF-01, RF-02 as above |
| D6 tiers | 5 tiers at 350/550/650/750 |
| D7 ML PD bands | 5% / 12% / 25% |

## What-If simulator

`simulator/whatif.py` builds a hypothetical copy of the applicant `h` months ahead:

1. **Status quo.** Transactions replay the last 6 complete months cyclically, and bills replay the same month one year earlier, including their payment lag. This is the "if nothing changes" baseline.
2. **Scenario overlay.** Each scenario edits only the hypothetical rows (flag `hyp=True`): saving boost (retain money otherwise spent on dining/shopping/cash), autopay (future selected bills paid on the due date), overspend, delinquency, new debt, employment change, spend cut, smoothing, card paydown, recurring investment.
3. Both copies go through the same `compute_features` + `evaluate`. The result reports the change vs today and vs the no-change baseline, per-rule changes and products gained or lost.

History is never edited. The API stores only a `simulator_events` log row and an audit entry, never a score.

**Why results differ from the use-case's illustrative figures** (+35, +60, −50, −110). Rules are banded and time-windowed, so a scenario moves the score only when it pushes a measured value across a band edge. On a 200-applicant live sample the median effects vs the no-change baseline were: saving boost 0 (13% of applicants moved; mean +3), autopay 0 (7% moved, because three months of on-time bills rarely shift a 12-month rate across a band), overspend −80 (88% moved), delinquency −75 (77% moved). Applicants already at 0 on 3.1/3.4 cannot lose more, and the 1000 cap hides gains for top scorers. A temporary 3-month saving boost can even cost 2.3 points (5 of 200): the step change in net cash flow raises its 6-month volatility. That is the official rule working as written, and it is reported rather than hidden.

## Counterfactual (target achievement)

`counterfactual/search.py` tries horizons 1, 2, 3, 6, 9 and 12 months. At each horizon it first tries waiting, then 1, 2 and 3 levers at their strongest level, then shrinks each lever to its smallest sufficient level. Preference goes to the shortest horizon, then fewer levers, then lower effort, then smaller levels. Levers are autopay, spend cut, saving boost, smoothing, card paydown and recurring investment. Plans never change age, city, past records or education, and never suggest earning more, buying a home or opening credit. Every returned plan is the result of an actual re-score. Points per step are measured by removing that step. Dated milestones (late payments ageing out, flags expiring, tenure bands) are listed separately.
