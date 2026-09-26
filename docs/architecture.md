# Architecture

```
 Browser (React + TS, Vite build)            Mock partner bank (FastAPI, :8001)
        │  /api/* (Bearer token)                    ▲  X-API-Key, pseudonymous applicant_ref only
        ▼                                           │
 AltCredit API (FastAPI, :8000) ── bank client ─────┘
   ├─ auth (PBKDF2 hashes, HMAC-signed tokens, roles: user / lender / admin)
   ├─ services.build_profile(user) ──┐
   │                                 ▼
   │   features.compute_features(raw records, as_of)      ← only records dated before as_of
   │        │
   │        ├─► rules.engine.evaluate()  ═══► POLICY SCORE 0-1000, tier, decision, reason records   (authoritative)
   │        │                                    │
   │        │                                    ├─► recommendations.eligibility (score ≥ product min_score)
   │        │                                    └─► explainability (text built from the same reason records)
   │        │
   │        └─► ml.pd_vector() ─► PD model ─► PD, ML Risk Score, signals ─┐
   │                                                                       ├─► agreement (review flag only)
   │            rule tier + ML band ──────────────────────────────────────┘
   │            propensity model ─► ordering of already-eligible products
   │
   ├─ simulator.whatif (hypothetical overlay on a copy; never writes history)
   ├─ counterfactual.search (levers × horizons, each candidate re-scored by the real engine)
   ├─ offers / lenders (anonymised until acceptance), applications (→ bank)
   └─ SQLite (WAL): raw data, append-only score history, ML predictions, offers, audit log
```

## Principles

* **Rule first.** `rules/engine.py` never imports anything from `ml/`. The ML layer receives the finished rule result and can only attach a review flag. `agreement()` always returns `rule_changed: False`, and a test enforces it.
* **One source of truth for explanations.** Each rule returns a reason record (`id, points, band, value, text, evidence`). The UI factor bars, the trace, the PDF, the JSON export and the lender view are all rendered from those records, so an explanation cannot disagree with the score.
* **Central policy.** Every threshold, band, open decision (D1–D7), tier edge, ML band, lender default and simulator default lives in `backend/app/rules/policy.py` and is served read-only at `GET /api/policy`.
* **As-of discipline.** Every feature is computed at an explicit as-of date from records strictly before it (live applicants: 2026-06-01, because the live ledger ends in May 2026; historical applicants: the application date; uploads: the first of the month after their last transaction).
* **Performance.** Raw records load into column arrays (`UserData`). One rule evaluation takes about 3 ms, a full profile with ML about 11 ms and an API profile call about 35–60 ms. Models load once at startup (`lifespan`) and are never retrained per request. Each user's data sits in a small LRU cache that is invalidated on refresh.

## Processes

| Process | Command | Notes |
|---|---|---|
| API + built UI | `uvicorn app.main:app --port 8000` (from `backend/`) | serves `frontend/dist` as an SPA when present |
| Mock bank | `MOCKBANK_API_KEY=… uvicorn mockbank.app:app --port 8001` | own SQLite at `mockbank/data/bank.db` |
| Vite dev server (optional) | `npm run dev` in `frontend/` | proxies `/api` to :8000 |

`scripts/run.sh` starts both backends with a shared, per-run bank API key.

## Frontend

`src/layouts/UserLayout.tsx` fetches the applicant's profile once and shares it with its pages; `LenderLayout.tsx` hosts the lender and admin portals. Every value on screen comes from the API: scores, tiers, eligibility, products, ML results and thresholds (`/api/policy`, `/api/products`). The only client-side arithmetic is presentation, such as bar widths.

User pages: Dashboard, Score details (factors / trace / ML / data quality), Products, What-If, Target, Offers, Applications, Report, Profile, plus Sign-in and Onboarding (register + upload).
Lender pages: Dashboard, Candidates, Candidate detail, Sent offers, Analytics. Admin: Platform (ingestion runs, rule catalog, audit, single ingestion), Applicants, Analytics.
