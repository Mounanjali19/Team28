#!/usr/bin/env bash
# Start the whole AltCredit demo: mock partner bank (:8001) + API serving the built UI (:8000).
#   ./scripts/run.sh            # production-style: builds the frontend once, one URL http://127.0.0.1:8000
#   ./scripts/run.sh --dev      # also starts the Vite dev server on http://127.0.0.1:5173
# Needs: backend/.venv (or .venv) with requirements installed, a seeded database (python backend/scripts/seed.py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in "$ROOT/.venv/bin/python" "$ROOT/backend/.venv/bin/python"; do [[ -x "$c" ]] && PY="$c" && break; done
fi
PY="${PY:-python3}"

[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

# One shared key between AltCredit and the mock bank, generated per run unless provided.
KEY="${ALTCREDIT_BANK_API_KEY:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(24))')}"
export ALTCREDIT_BANK_API_KEY="$KEY" MOCKBANK_API_KEY="$KEY"
# Token signing secret: ephemeral per run unless set (sessions end when the server restarts).
export ALTCREDIT_SECRET_KEY="${ALTCREDIT_SECRET_KEY:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')}"

if [[ ! -f "${ALTCREDIT_DB:-$ROOT/data/altcredit.db}" ]]; then
  echo "No database yet. Run: $PY backend/scripts/seed.py" >&2
  exit 1
fi

if [[ "${1:-}" != "--dev" && ! -f frontend/dist/index.html ]]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

"$PY" -m uvicorn mockbank.app:app --host 127.0.0.1 --port 8001 --log-level warning &
pids+=($!)
(cd backend && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
pids+=($!)
if [[ "${1:-}" == "--dev" ]]; then
  (cd frontend && npm run dev -- --host 127.0.0.1) &
  pids+=($!)
  echo "UI (dev): http://127.0.0.1:5173"
fi
echo "AltCredit: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs   Mock bank: http://127.0.0.1:8001/docs"
wait
