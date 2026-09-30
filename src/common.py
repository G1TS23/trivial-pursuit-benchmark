"""Chemins et helpers partagés par les scripts du pipeline."""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

# --- Arborescence du data lake (médaillon) ---------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

BRONZE_DIR = DATA / "bronze"
SILVER_DIR = DATA / "silver"
GOLD_DIR = DATA / "gold"

BRONZE_CSV = BRONZE_DIR / "questions_raw.csv"
SILVER_QUESTIONS = SILVER_DIR / "questions" / "questions.parquet"
SILVER_RESPONSES_DIR = SILVER_DIR / "responses"          # partitionné model=/prompt=
GOLD_DB = GOLD_DIR / "gold.duckdb"

CONFIG_DIR = ROOT / "config"
PROMPTS_YAML = CONFIG_DIR / "prompts.yaml"


def ensure_dirs() -> None:
    for d in (BRONZE_DIR, SILVER_DIR, GOLD_DIR,
              SILVER_QUESTIONS.parent, SILVER_RESPONSES_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --- Identité stable d'une question --------------------------------------
def question_id(question: str, correct_answer: str) -> str:
    h = hashlib.sha1(f"{question}||{correct_answer}".encode("utf-8"))
    return h.hexdigest()[:16]


# --- Normalisation pour le matching des réponses ouvertes ---------------
_ARTICLES = re.compile(r"^(the |a |an |le |la |les |l')", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.strip().lower()
    t = _ARTICLES.sub("", t)
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


# --- Lecture d'env ------------------------------------------------------
def load_dotenv(path: Path | None = None) -> None:
    """Charge ROOT/.env dans os.environ (les vraies variables d'env priment).

    Mini-parseur sans dépendance : `CLE=valeur`, `#` = commentaire,
    guillemets optionnels. Suffisant pour ce projet.
    """
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if not val.startswith(('"', "'")) and " #" in val:
            val = val.split(" #", 1)[0].strip()   # commentaire en fin de ligne
        os.environ.setdefault(key.strip(), val.strip('"').strip("'"))


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def models_from_env() -> list[str]:
    raw = env("MODELS", "")
    return [m.strip() for m in raw.split(",") if m.strip()]
