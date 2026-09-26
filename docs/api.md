# API

Interactive docs: `http://127.0.0.1:8000/docs` (AltCredit) and `http://127.0.0.1:8001/docs` (mock bank).

Auth: `POST /api/auth/login` or `/api/auth/demo-login` returns `{token, role, user_id, lender_id, …}`. Send `Authorization: Bearer <token>` on every call. Roles: `user` (own record only), `lender`, `admin`. Tokens are HMAC-SHA256 signed with `ALTCREDIT_SECRET_KEY` and expire after `ALTCREDIT_TOKEN_TTL_MINUTES`.

## Applicant

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | multipart: `username`, `password`, `profile` (JSON), `transactions` (CSV/JSON), optional `bills`; validates, stores, scores |
| GET | `/api/users/{id}/score` | full profile: `policy` (score, raw_score, tier, decision, 14 reason records, trace, data_quality), `explanation`, `products`, `recommendations`, `next_locked_product`, `ml`, `propensity`, `timing_ms` |
| POST | `/api/users/{id}/score` | recompute from raw data and append to score history |
| GET | `/api/users/{id}/factors` | rule-by-rule trace only |
| GET | `/api/users/{id}/products` | eligibility for every catalog product + ordered recommendations |
| GET | `/api/users/{id}/history` | stored score history (append-only) |
| GET | `/api/users/{id}/data-summary` | monthly income/spend and bill counts used by the engine |
| GET | `/api/ml/{id}` | ML validation block alone |
| GET | `/api/simulator/presets` | official scenarios + extras |
| POST | `/api/users/{id}/simulate` | `{scenarios:[{type, params}], horizon_months?, preset?}` → today / baseline / simulated, deltas, per-rule changes |
| POST | `/api/users/{id}/counterfactual` | `{product_id}` → status, verified plan, milestones |
| GET | `/api/reports/{id}` | transparency report PDF |
| GET | `/api/users/{id}/export` | the profile as a JSON download |
| GET | `/api/users/{id}/offers` | offers to this applicant |
| POST | `/api/offers/{offer_id}/respond` | `{action: view|accept|reject}`; accept re-checks the score and reveals the contact to that lender |
| POST | `/api/applications` | `{product_id, offer_id?, requested_amount?}` → bank pre-approval + submission |
| GET | `/api/applications`, `/api/applications/{id}` | list; refresh status from the bank |

## Lender

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/lenders/dashboard` | KPIs |
| GET | `/api/lenders/candidates` | filters: `score_min` (default 650), `score_max`, `tiers[]`, `eligible_for`, `validation[]`, `review_flag`, `pd_min/pd_max`, `employment[]`, `income_min/max`, `city_tier[]`, `data_quality[]`, `exclude_offered`; `sort=score|pd|propensity|income`, `order`, `page`, `page_size` |
| GET | `/api/lenders/candidates/{id}` | risk profile (masked until acceptance) + your offers |
| POST | `/api/offers` | `{user_id, product_id, interest_rate?, amount?, expiry_days?, message?}`; own products only, score ≥ minimum, identity ≥ 0.8, no duplicate open offer |
| POST | `/api/offers/bulk` | `{user_ids[], product_id, …, campaign_name?}`; non-qualifiers and POOR data quality are skipped with a reason |
| GET | `/api/lenders/offers` | sent offers + campaigns |
| GET | `/api/lenders/analytics?population=live|historical|all_pool` | distributions, agreement, reach, observed default by tier |

## Platform

`GET /api/health`, `/api/policy`, `/api/rules`, `/api/features/catalog`, `/api/products`, `/api/ml/metrics`; admin: `POST /api/ingestion`, `GET /api/admin/ingestion-runs`, `GET /api/admin/audit` (users see only their own entries).

## Mock bank (separate service, `X-API-Key` required)

| Method | Path | Behaviour |
|---|---|---|
| POST | `/bank/preapproval` | receives only `applicant_ref` (salted hash), product, policy score, tier, review flag, amount → `PRE_APPROVED`, `REFERRED` (enhanced review) or `DECLINED` (score below minimum) |
| POST | `/bank/apply` | `{preapproval_id}` → `SUBMITTED` |
| GET | `/bank/application/{id}` | `SUBMITTED` → `UNDER_REVIEW` over `MOCKBANK_REVIEW_SECONDS`, then `APPROVED` (pre-approved) or `MANUAL_REVIEW` (referred) |

Errors are JSON `{detail}` with 401/403 (auth), 404, 409 (state conflict, e.g. offer already answered), 422 (validation, ineligible) and 503 (bank unreachable).
