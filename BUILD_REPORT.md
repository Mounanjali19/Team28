# AltCredit build report (2026-09-26)

## What was built
A runnable, end-to-end, rule-first alternative credit application. The source is in this folder, a git repo with 2 local commits.

- **Rule engine (authoritative):** the 14 official rules produce a 0–1000 policy score, tier, decision, eligibility and reason records. All thresholds and the D1–D7 defaults live in `backend/app/rules/policy.py`.
- **ML (secondary):** Case 1 PD, labelled "ML Risk Score = 1000 × (1 − PD)"; the agreement engine, with review flags only; Case 2 propensity, which only orders eligible products. Models load at startup.
- **What-If:** status-quo replay plus a hypothetical overlay, covering the 4 official scenarios and 6 more. History is never written.
- **Counterfactual:** horizons of 1–12 months and 6 actionable levers. Every plan is re-scored and dated milestones are listed.
- **Applicant app (11 screens):**
  - sign-in with a demo picker, and onboarding with upload
  - dashboard, score details (factors / trace / ML / data quality), products, What-If, target, offers
  - bank applications, report (PDF + JSON), profile/data
- **Lender portal:** dashboard, candidates (all filters, default 650+, masked, bulk select), candidate detail, sent offers and campaigns, analytics with model metrics. Admin covers ingestion runs, the rule catalog, audit and single-applicant ingestion.
- **Mock bank:** a separate service protected by an API key. It receives a pseudonymous reference only.
- **Platform:** SQLite with append-only score history, an audit log, ingestion validation records, PBKDF2 auth and signed tokens.

## How to run
See README.md. The steps are: install the venv, run `backend/scripts/seed.py` (about 6 minutes; the ~690 MB database is not copied here), build the frontend, then `./scripts/run.sh`. Open http://127.0.0.1:8000, with API docs at /docs.

Demo logins are one-click on the sign-in page. The password is `ALTCREDIT_DEMO_PASSWORD`, default `AltCredit#2026` for the synthetic demo accounts.

## Verified in the build environment
- Full seed:
  - v2 data: 5,500 users, 4.2 M transactions, 448 k bills, 7 validation findings
  - official sample: 500 users
- **Backend tests: 143 passed.** Coverage:
  - every band edge
  - hand-computed ground truth for 3 applicants
  - What-If direction and immutability
  - counterfactual verification
  - ML leakage and temporal split
  - the full API flow, including the mock bank
- **Browser tests: 2 Playwright flows passed.** Every page was checked at desktop width and on phone for console errors.
- **PD model:** holdout AUC 0.828 (random forest 0.807, policy score alone 0.686, shuffled labels 0.43); ECE 0.018.
- **Propensity model:** AUC 0.617, top-decile lift 2.1×.
- **Speed:** rules about 3 ms per applicant, profile with ML about 11 ms, API profile call 35–60 ms.
- **Fixed during self-audit:**
  - `/api/ml/metrics` was shadowed by `/api/ml/{user_id}`
  - SPA fallback now refuses path traversal and unknown `/api/*` paths
  - mobile nav layout

## Not verified
- A deployment outside this container. Docker was not built.
- Visual regression beyond manual screenshot review.

## Findings you should know
- **PD model leans on autopay.** Autopay use is the strongest predictor in the synthetic data, so a clean payer without autopay can get a high PD. Some collinear late-payment coefficients have odd signs. Rules are unaffected. Details: docs/ml-validation.md.
- **What-If effects are banded.** Live-sample medians vs doing nothing: saving boost 0, autopay 0, overspend −80, delinquency −75. The +35/+60 examples rarely reproduce, and a temporary saving boost can lower rule 2.3. Details: docs/rule-engine.md.
- **Score distribution is top-heavy.** The live median is 950 and 39% of applicants are capped at 1000. Weights were not changed.
