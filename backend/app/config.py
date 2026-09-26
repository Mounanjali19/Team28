"""Runtime settings, read from environment variables (no secrets in code)."""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(env: str, default: Path) -> Path:
    return Path(os.environ.get(env, str(default))).expanduser().resolve()


def _first_existing(*candidates: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


class Settings:
    def __init__(self):
        self.db_path = _path("ALTCREDIT_DB", REPO_ROOT / "data" / "altcredit.db")
        self.dataset_dir = _path("ALTCREDIT_DATASET_DIR", _first_existing(
            REPO_ROOT.parent / "Datasets_AltCredit_v2", REPO_ROOT / "data" / "raw" / "Datasets_AltCredit_v2",
            Path("/mnt/project-files/Datasets_AltCredit_v2")))
        self.legacy_dataset_dir = _path("ALTCREDIT_LEGACY_DATASET_DIR", _first_existing(
            REPO_ROOT.parent / "Datasets_AltCredit", REPO_ROOT / "data" / "raw" / "Datasets_AltCredit",
            Path("/mnt/project-files/Datasets_AltCredit")))
        self.models_dir = _path("ALTCREDIT_MODELS_DIR", REPO_ROOT / "models")
        self.reports_dir = _path("ALTCREDIT_REPORTS_DIR", REPO_ROOT / "reports")
        self.bank_api_url = os.environ.get("ALTCREDIT_BANK_API_URL", "http://127.0.0.1:8001")
        self.bank_api_key = os.environ.get("ALTCREDIT_BANK_API_KEY", "")
        self.cors_origins = os.environ.get("ALTCREDIT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        self.token_ttl_minutes = int(os.environ.get("ALTCREDIT_TOKEN_TTL_MINUTES", "480"))
        secret = os.environ.get("ALTCREDIT_SECRET_KEY")
        if not secret:
            # Ephemeral key: sessions do not survive a restart, but nothing is hard-coded.
            secret = secrets.token_hex(32)
            logging.getLogger("altcredit").warning("ALTCREDIT_SECRET_KEY not set; using an ephemeral key for this process")
        self.secret_key = secret


settings = Settings()

logging.basicConfig(level=os.environ.get("ALTCREDIT_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("altcredit")
