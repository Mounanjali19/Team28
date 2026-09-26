# Data model

SQLite in WAL mode. Schema: `backend/app/database/schema.sql`. Database: `data/altcredit.db` (about 690 MB after seeding, gitignored). The mock bank keeps its own database at `mockbank/data/bank.db`.

## Raw data (ingested, validated)

| Table | Content |
|---|---|
| `users` | one row per applicant: demographics, `cohort` (live / historical / official_sample / uploaded), `as_of_date`, `match_confidence`, `demo_label`, source, ingestion run |
| `contacts` | synthetic name, phone, locality (the only PII-like fields; masked for lenders until acceptance) |
| `employment_spells`, `residence_spells` | dated spells |
| `transactions` | date, amount, category, CREDIT/DEBIT, subtype, balance_after, source |
| `obligations` | bills: type (rent/utility/telecom/emi/card_min), due date, paid date, amounts, autopay |
| `credit_accounts`, `card_statements` | revolving/loan lines and monthly card statements |
| `life_events` | address changes, credit inquiries |
| `lenders`, `products` | catalog, read from `product_catalog.json` / `lenders.json` |
| `historical_applications`, `historical_offers`, `simulator_events` | outcomes and behaviour used to train the ML models |
| `ingestion_runs`, `ingestion_errors` | every load with its validation findings (check code, severity, count, sample row) |

Validation (`ingestion/validation.py`) covers required columns, types, enum values, duplicate keys, future dates, non-positive amounts, unknown user ids, and id-mapping confidence. Rows that fail are dropped and counted, never silently fixed. The official sample format (`Datasets_AltCredit`) goes through the same validators via an adapter. That format has no bill table, so Rent/Utility/Telecom/Loan EMI debits become bills, and a "Late" status is treated as paid 15 days after the due date.

## Derived data (application)

| Table | Content |
|---|---|
| `scores` | **append-only** score history: score, raw score, tier, decision, data quality, rule version, trigger, latency, full `result_json`; `is_current` marks the latest |
| `score_factors` | the 14 reason records per stored score |
| `ml_predictions` | PD, band, agreement, review flag, confidence, model version, propensities |
| `offers`, `offer_events`, `campaigns` | offer lifecycle: sent → viewed → accepted/rejected/expired/withdrawn |
| `reveals` | which lender may see which applicant's contact (written on acceptance) |
| `bank_applications` | pre-approval id, bank reference, status, payload actually sent to the bank |
| `counterfactual_requests` | every target plan with its result |
| `auth_accounts` | username, PBKDF2-SHA256 hash (120k iterations, per-user salt), role, linked user/lender |
| `audit_logs` | who did what when: logins, score calculations, simulations, counterfactuals, offers, responses, reports, bank calls, with rule/model version |

Simulations never write to `scores`. They add a `simulator_events` row (source `app`) and an audit entry.

## In-memory form

`features/userdata.py` `UserData` holds one applicant's records as numpy column arrays. Simulated rows carry `hyp=True`, and history is copied, never edited.
