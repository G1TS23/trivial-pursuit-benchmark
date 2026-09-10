"""Étape 2a — Nettoyage BRONZE -> SILVER (questions).

data/bronze/questions_raw.csv  ->  data/silver/questions/questions.parquet

Transformations :
  - dédoublonnage sur question_id
  - types castés ; `difficulty` en catégoriel ordonné easy < medium < hard
  - `incorrect_answers` : JSON -> liste
  - construction d'un QCM déterministe : `options` (liste ordonnée) +
    `correct_letter` (A/B/C/D...). L'ordre est mélangé avec un seed dérivé
    du question_id => stable d'un run à l'autre, sans biais de position.
  - métadonnées utiles à l'analyse : `question_len`, `n_options`

Aucune réponse de modèle ici : les réponses IA vivent dans
data/silver/responses/ (voir enrich_lmstudio.py).
"""
from __future__ import annotations

import argparse
import json
import random
import string

import polars as pl

from common import BRONZE_CSV, SILVER_QUESTIONS, ensure_dirs

LETTERS = list(string.ascii_uppercase)
DIFF_ORDER = ["easy", "medium", "hard"]


def build_options(qid: str, correct: str, incorrect: list[str]) -> dict:
    rng = random.Random(int(qid, 16))
    opts = [correct, *incorrect]
    rng.shuffle(opts)
    letter = LETTERS[opts.index(correct)]
    return {
        "options": opts,
        "correct_letter": letter,
        "n_options": len(opts),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", default=str(BRONZE_CSV))
    ap.add_argument("--out", default=str(SILVER_QUESTIONS))
    args = ap.parse_args()

    ensure_dirs()
    df = pl.read_csv(args.src)

    before = len(df)
    df = df.unique(subset=["question_id"], keep="first")
    print(f"dédoublonnage : {before} -> {len(df)} lignes")

    incorrect = [json.loads(x) for x in df["incorrect_answers"].to_list()]
    built = [
        build_options(qid, corr, inc)
        for qid, corr, inc in zip(
            df["question_id"].to_list(),
            df["correct_answer"].to_list(),
            incorrect,
        )
    ]

    out = df.with_columns(
        pl.Series("incorrect_answers", incorrect),
        pl.Series("options", [b["options"] for b in built]),
        pl.Series("correct_letter", [b["correct_letter"] for b in built]),
        pl.Series("n_options", [b["n_options"] for b in built], dtype=pl.Int8),
        pl.col("question").str.len_chars().alias("question_len"),
        pl.col("difficulty").cast(pl.Enum(DIFF_ORDER)),
        pl.col("type").cast(pl.Categorical),
        pl.col("category").cast(pl.Categorical),
    )

    out.write_parquet(args.out)
    print(f"écrit : {args.out}  ({len(out)} questions)")
    print(out.group_by("difficulty").len().sort("difficulty"))
    print(out.group_by("type").len())


if __name__ == "__main__":
    main()
