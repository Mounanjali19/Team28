# Assumptions, decisions and limitations

## Guardrails honoured

* Synthetic data only. Names, phones and localities are generated. No real bureau, bank or payment API is called; the partner bank is a local mock.
* No deep learning. Both models are logistic regressions with published coefficients.
* No hard-coded outcomes. Scores, tiers, eligibility, recommendations and ML results are computed per request from raw records. Product data comes from the catalog JSON. Thresholds come from `policy.py` (served at `/api/policy`).
* No hard-coded secrets. The token key and the bank API key come from the environment, or are generated per run. Passwords are stored only as PBKDF2 hashes. The one documented default is the **demo password** for the synthetic seeded accounts (`AltCredit#2026`, overridable with `ALTCREDIT_DEMO_PASSWORD`), kept so a reviewer can sign in. Set your own before sharing a deployment, or turn off one-click demo login with `ALTCREDIT_DEMO_MODE=0`.
* The simulator never modifies history (enforced by tests).
* Rule weights were not changed to reshape the score distribution.

## Rulebook v0.1 defaults (open decisions D1–D7)

See `rule-engine.md`. All are in `backend/app/rules/policy.py` and appear on every score (`policy.open_decisions`) and in the PDF.

## Project decisions beyond the official table

| Topic | Decision |
|---|---|
| As-of date | live applicants 2026-06-01 (ledger ends May 2026); historical: application date; uploads/official sample: first of the month after the last transaction; only records strictly before the as-of date count |
| No credit line | 3.3 scores a neutral 70 and raises `NO_CREDIT_LINE` (absence of credit is not penalised) |
| Line without statement | 3.3 provisional 70, `UTILIZATION_UNVERIFIED` |
| No bills in 24 months | 3.4 scores 150 and raises `THIN_REPAYMENT_HISTORY` (no delinquency observed); ML confidence is withheld |
| Living with family | 1.2 = 30 |
| Students / unemployed | 1.1 = 0 |
| Gig / freelance tenure | min(spell months, consecutive months with income) |
| Income | declared income, unless it exceeds 1.5× verified income, in which case verified income is used (`INCOME_CONFLICT`); if nothing is declared, verified income (`INCOME_VERIFIED`); otherwise rules that need income score 0 |
| Official sample format | bills derived from Rent/Utility/Telecom/Loan EMI debits; "Late" status = paid 15 days late |
| Identity | match < 0.6: scored but REFER, nothing eligible; 0.6–0.8: eligible but no lender offers |
| Offers | only the lender's own products, score ≥ minimum at push and again at acceptance (otherwise withdrawn), one open offer per product, 30-day default expiry, POOR data quality skipped in bulk |
| Uploads | CSV or JSON only; PDF/OCR statements are out of scope |

## Known limitations

* **Score distribution is top-heavy.** Live median is 950; 39% of live applicants hit the 1000 cap (raw totals up to 1320). This comes from the official weights and the synthetic data (70% of applicants have no credit line and get a neutral 70). Weights were not changed, as instructed. Consequence: the default lender filter (650+) returns most of the pool, and What-If gains for top applicants are hidden by the cap (the UI shows the raw change).
* **What-If effects are banded.** Scenarios move the score only when a measured value crosses a band edge. The illustrative figures in the use case (+35, +60, −50, −110) are not reproduced exactly for most applicants; see the measured distribution in `rule-engine.md`. A temporary saving boost can lower 2.3 (volatility) for applicants near a band edge. This is the official rule behaving as written.
* **ML model behaviour.** The PD model leans heavily on autopay usage, and some collinear late-payment coefficients have counter-intuitive signs. Propensity AUC is 0.62. See `ml-validation.md`. None of this affects the policy decision.
* **Official sample applicants** have only a few months of data and no bill table, so they all score with POOR data quality (median 460).
* **Demo auth.** Tokens are stateless and cannot be revoked before expiry. There is no rate limiting, no password reset and no CSRF protection (tokens live in `sessionStorage` and are sent as headers, not cookies). That is appropriate for a local demo, not for production.
* **Single-node SQLite.** It suits the demo (6,000 applicants, 4.2 M transactions). A multi-user deployment would move to Postgres.
* **Candidate search** filters in Python over the scored pool (about 500–1,000 rows). A larger pool would need SQL-side filtering and indexes.
