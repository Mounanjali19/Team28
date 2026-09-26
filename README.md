# AltCredit

A working prototype of rule-first alternative credit scoring for people without a credit bureau file.

- **Rule engine (authoritative).** Fourteen published rules turn raw transactions, bills, card statements and life events into a **0–1000 policy score**, a risk tier and product eligibility. Every point can be traced to a rule and to the records behind it.
- **ML (secondary).** A Case 1 probability-of-default model and a Case 2 offer-acceptance model validate the rule decision. They flag agreement or disagreement (enhanced review / second look) and order products. They **never** change the score, tier or eligibility. The ML output is shown separately as the **"ML Risk Score" = 1000 × (1 − PD)** and is never called a credit score.
- **Applicant app** covering the score, factor analysis, score trace, What-If simulator, target plan (counterfactual), offers, bank applications, the transparency report (PDF + JSON) and profile/data.
- **Lender portal** covering a dashboard, anonymised candidate search (default policy-score range 650+), candidate detail, single and bulk offers, sent offers and analytics. Contacts are revealed only after the applicant accepts.
- **Mock partner bank**, a separate API-key-protected service: `POST /bank/preapproval`, `POST /bank/apply`, `GET /bank/application/{id}`.

All people, lenders and bank responses are **synthetic**. No real bureau or banking API is called.

## Quick start

Requirements: Python 3.11+, Node 20+.

```bash
# 1. Python environment
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

# 2. Build the database: ingest + validate datasets, train ML, score everyone, create demo logins (~6 min)
#    Reads ../Datasets_AltCredit_v2 and ../Datasets_AltCredit (override with ALTCREDIT_DATASET_DIR / ALTCREDIT_LEGACY_DATASET_DIR)
.venv/bin/python backend/scripts/seed.py

# 3. Frontend
(cd frontend && npm install && npm run build)

# 4. Run mock bank (:8001) + API and UI (:8000)
bash scripts/run.sh         # open http://127.0.0.1:8000     (API docs: /docs)
bash scripts/run.sh --dev   # additionally runs Vite on http://127.0.0.1:5173 with hot reload
```

`scripts/run.sh` generates the AltCredit↔bank API key and the token-signing key for each run unless they are set in `.env` (see `.env.example`).

## Demo accounts

On the sign-in page, click any demo applicant or lender (one-click demo login, `ALTCREDIT_DEMO_MODE=1`). The seeded accounts all share the password in `ALTCREDIT_DEMO_PASSWORD` at seed time. If that is unset, the password is `AltCredit#2026`. That default exists for the synthetic demo only; set your own before sharing a deployment.

| Login | Purpose | Seeded result |
|---|---|---|
| `demo.strong` | strong applicant | 970, T5 |
| `demo.moderate` | moderate | 575, T3 |
| `demo.borderline` | just under the 750 edge | 745, T4 |
| `demo.highrisk` | high risk, rule and ML agree | 330, T1 |
| `demo.nocredithistory` | no credit line (neutral 3.3) | 1000, T5 |
| `demo.missingdata` | data gaps, LIMITED data quality | 890 |
| `demo.disagreement` | rule-eligible, ML PD 80.8% → enhanced review | 660, T4 |
| `demo.officialsample` | applicant from the official sample file | 740 |
| `anchorline`, `northbridge`, `pinewood`, `suryoday`, `kestrel`, `vantage` | lenders | |
| `admin` | platform: ingestion runs, rule catalog, audit, single-applicant ingestion | |

Scores are recomputed from raw data by the engine. The table shows what the seed produced; nothing in the UI is hard-coded.

## Demo flow (10 minutes)

1. Sign in as **Disagreement**. The dashboard shows policy score 660 (Low Risk, 3 eligible products) and, separately, ML Risk Score 192 with "Elevated risk: enhanced review".
2. Open **Score details**. Walk the 14-rule breakdown with evidence, the score trace, the ML validation tab and the data-quality tab.
3. Open **What-If** and run the four official scenarios. The simulator shows today, "if nothing changes" and "with this change", plus each rule that moved. History is never modified.
4. Open **Target** and choose Lifestyle Rewards Card. The app shows a verified minimal plan (levers, months, points per step) and dated milestones.
5. Open **Report** and download the PDF and JSON transparency report.
6. Sign out and sign in as **Pinewood** (lender). Candidates are masked and ranked by policy score. Filter by product, tier or validation state. Open a candidate and send an offer, or select several for a campaign.
7. Sign in as **Borderline**. Open **Offers**, then Accept. The score is re-checked and the contact is revealed to Pinewood. Click **Apply with the bank** and the mock bank pre-approves the application; **Check status** moves it from under review to approved.
8. Back as Pinewood, **Sent offers** shows the accepted offer with the contact now visible. **Analytics** shows score, tier and PD distributions, agreement, observed default by tier and model validation metrics.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q          # 143 tests: bands, ground truth, what-if, leakage, API
cd frontend && npx tsc --noEmit -p . && npm run build   # typecheck + build
bash scripts/run.sh & (cd frontend && npx playwright test)  # browser flow against the running stack
```

The browser test uses Playwright's Chromium. Set `PW_CHROMIUM=/path/to/chromium` to use a preinstalled one.

## Layout

```
backend/app/rules/policy.py     every threshold, band, open decision (D1-D7), tier and ML band: one central config
backend/app/features/           raw records -> 14 factor values (as-of aware, no future data)
backend/app/rules/engine.py     factor values -> points, reason records, score, tier, data quality
backend/app/ml/                 PD + propensity models, agreement engine, training (temporal split)
backend/app/simulator/          What-If projection (status-quo replay + hypothetical overlay)
backend/app/counterfactual/     target achievement search, verified by re-scoring
backend/app/api/                FastAPI routers; backend/app/main.py serves the built UI too
backend/app/database/schema.sql SQLite schema (append-only score history, audit log)
backend/scripts/seed.py         ingest -> train -> score -> demo accounts
mockbank/app.py                 mock partner bank (separate process, API key)
frontend/                       React + TypeScript + Vite
docs/                           architecture, rule engine, ML validation, API, data model, testing, assumptions
```

See [docs/](docs/) for the details and [docs/assumptions.md](docs/assumptions.md) for every judgement call and known limitation.
