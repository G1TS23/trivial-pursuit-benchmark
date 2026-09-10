"""Étape 2b — Enrichissement IA -> SILVER (responses).

Pour chaque (question x modele x prompt actif), interroge un modèle servi par
LM Studio et enregistre la réponse brute + les colonnes imposées par le sujet :
    ai_answer       réponse générée
    ai_correct      booléen (réponse == bonne réponse)
    response_time   temps de génération en secondes (wall-clock)

+ colonnes de rigueur : model, prompt_id, prompt_text, run_id, ran_at,
  raw_answer, is_parsable, answer_len, match_method, + stats natives LM Studio.

Sortie partitionnée (résumable) :
    data/silver/responses/model=<model>/prompt=<prompt_id>/part.parquet

Le script est IDEMPOTENT : au démarrage il lit ce qui existe déjà et ne
rejoue que les triplets (question_id, model, prompt_id) manquants. Une coupure
ne fait donc rien perdre. Boucle modèle par modèle (un seul modèle chargé à la
fois dans LM Studio) pour garder des temps de réponse comparables.

Pré-requis : serveur LM Studio démarré (`lms server start`) + modèles
téléchargés (`lms get ...`). Voir README.
"""
from __future__ import annotations

import argparse
import os
import re
import string
import time
import uuid
from datetime import datetime, timezone

import polars as pl
import yaml
from rapidfuzz import fuzz

from common import (
    PROMPTS_YAML,
    SILVER_QUESTIONS,
    SILVER_RESPONSES_DIR,
    ensure_dirs,
    models_from_env,
    normalize_answer,
)

LETTERS = string.ascii_uppercase
FUZZY_THRESHOLD = 88          # >= => considéré correct en mode "open"


# --------------------------------------------------------------------------
# Client LM Studio (SDK officiel `lmstudio`). Alternative : client `openai`
# pointé sur http://localhost:1234/v1 (voir README).
# --------------------------------------------------------------------------
class LMStudio:
    def __init__(self, host: str):
        import lmstudio as lms
        self._lms = lms
        self._lms.configure_default_client(host.replace("http://", "").replace("https://", ""))
        self._model = None
        self._model_key = None

    def load(self, model_key: str) -> None:
        if self._model_key == model_key:
            return
        if self._model is not None:
            try:
                self._model.unload()
            except Exception:
                pass
        print(f"  chargement du modèle : {model_key}")
        self._model = self._lms.llm(model_key)
        self._model_key = model_key
        # warm-up non mesuré (exclut le temps de chargement du 1er appel réel)
        try:
            self._model.respond("ok", config={"maxTokens": 1})
        except Exception:
            pass

    def ask(self, prompt: str, *, temperature: float, seed: int,
            max_tokens: int, json_schema: dict | None) -> tuple[str, float, dict]:
        cfg = {"temperature": temperature, "maxTokens": max_tokens, "seed": seed}
        kwargs = {"config": cfg}
        if json_schema is not None:
            kwargs["response_format"] = json_schema
        t0 = time.perf_counter()
        res = self._model.respond(prompt, **kwargs)
        elapsed = time.perf_counter() - t0
        stats = {}
        raw_stats = getattr(res, "stats", None)
        if raw_stats is not None:
            for k in ("tokens_per_second", "time_to_first_token_sec",
                      "total_time_sec", "predicted_tokens_count", "stop_reason"):
                v = getattr(raw_stats, k, None)
                if v is not None:
                    stats[k] = v
        return (res.content or "").strip(), elapsed, stats


# --------------------------------------------------------------------------
def load_prompts() -> list[dict]:
    cfg = yaml.safe_load(PROMPTS_YAML.read_text(encoding="utf-8"))
    return [p for p in cfg["prompts"] if p.get("active")]


def render_prompt(tpl: str, q: dict) -> str:
    options = q["options"]
    letters = list(LETTERS[: len(options)])
    options_block = "\n".join(f"{l}) {o}" for l, o in zip(letters, options))
    return tpl.format(
        question=q["question"],
        options_block=options_block,
        letters=", ".join(letters),
    )


LETTER_RE = re.compile(r"\b([A-H])\b")


def grade(mode: str, raw: str, q: dict) -> tuple[bool, str, bool, str]:
    """-> (ai_correct, ai_answer_normalisee, is_parsable, match_method)"""
    if mode == "mcq_letter":
        m = LETTER_RE.search(raw.upper())
        if not m:
            return False, raw, False, "letter_exact"
        letter = m.group(1)
        idx = LETTERS.index(letter)
        picked = q["options"][idx] if idx < len(q["options"]) else raw
        return letter == q["correct_letter"], picked, True, "letter_exact"

    # mode "open" : normalisation + fuzzy + inclusion
    norm_pred = normalize_answer(raw)
    norm_gold = normalize_answer(q["correct_answer"])
    if not norm_pred:
        return False, raw, False, "fuzzy"
    exact = norm_pred == norm_gold
    contained = norm_gold in norm_pred or norm_pred in norm_gold
    ratio = fuzz.token_set_ratio(norm_pred, norm_gold)
    return (exact or contained or ratio >= FUZZY_THRESHOLD), raw, True, "fuzzy"


def schema_for(mode: str, n_options: int) -> dict | None:
    if mode != "mcq_letter":
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "quiz_answer",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string",
                                          "enum": list(LETTERS[:n_options])}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }


def existing_keys(model: str) -> set[str]:
    root = SILVER_RESPONSES_DIR / f"model={model}"
    if not root.exists():
        return set()
    parts = list(root.glob("prompt=*/part.parquet"))
    if not parts:
        return set()
    df = pl.read_parquet(parts)
    return set(df["question_id"] + "|" + df["prompt_id"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="Ne traiter que les N premières questions (smoke test).")
    ap.add_argument("--models", default=None,
                    help="Liste de modèles (défaut : $MODELS).")
    ap.add_argument("--host", default=os.environ.get("LMSTUDIO_HOST", "http://localhost:1234"))
    args = ap.parse_args()

    ensure_dirs()
    seed = int(os.environ.get("SEED", "42"))
    temperature = float(os.environ.get("TEMPERATURE", "0"))
    max_tokens = int(os.environ.get("MAX_TOKENS", "64"))

    models = [m.strip() for m in args.models.split(",")] if args.models else models_from_env()
    if not models:
        raise SystemExit("Aucun modèle : renseigner MODELS dans .env ou --models")

    prompts = load_prompts()
    print(f"modèles  : {models}")
    print(f"prompts  : {[p['id'] for p in prompts]}")

    questions = pl.read_parquet(SILVER_QUESTIONS)
    if args.limit:
        questions = questions.head(args.limit)
    q_records = questions.to_dicts()
    run_id = uuid.uuid4().hex[:12]
    print(f"run_id   : {run_id}  ({len(q_records)} questions)")

    client = LMStudio(args.host)

    for model in models:
        done = existing_keys(model)
        client.load(model)
        for prompt in prompts:
            pid, mode, tpl = prompt["id"], prompt["mode"], prompt["template"]
            rows: list[dict] = []
            skipped = 0
            for q in q_records:
                if f"{q['question_id']}|{pid}" in done:
                    skipped += 1
                    continue
                text = render_prompt(tpl, q)
                schema = schema_for(mode, q["n_options"])
                try:
                    raw, elapsed, stats = client.ask(
                        text, temperature=temperature, seed=seed,
                        max_tokens=max_tokens, json_schema=schema,
                    )
                except Exception as exc:                       # noqa: BLE001
                    print(f"    [erreur] {model}/{pid} q={q['question_id']}: {exc}")
                    continue
                ok, ai_answer, parsable, method = grade(mode, raw, q)
                rows.append({
                    "question_id": q["question_id"],
                    "model": model,
                    "prompt_id": pid,
                    "prompt_text": tpl,
                    "prompt_mode": mode,
                    "run_id": run_id,
                    "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "raw_answer": raw,
                    "ai_answer": ai_answer,
                    "ai_correct": ok,
                    "is_parsable": parsable,
                    "answer_len": len(raw),
                    "match_method": method,
                    "response_time": elapsed,
                    "gen_time_sec": stats.get("total_time_sec"),
                    "ttft_sec": stats.get("time_to_first_token_sec"),
                    "tokens_per_second": stats.get("tokens_per_second"),
                })
            if not rows:
                print(f"  {model}/{pid} : rien à faire ({skipped} déjà présents)")
                continue
            out_dir = SILVER_RESPONSES_DIR / f"model={model}" / f"prompt={pid}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "part.parquet"
            new_df = pl.DataFrame(rows)
            if out_path.exists():
                new_df = pl.concat([pl.read_parquet(out_path), new_df], how="diagonal_relaxed")
            new_df.write_parquet(out_path)
            acc = new_df["ai_correct"].mean()
            print(f"  {model}/{pid} : +{len(rows)} (skip {skipped}) "
                  f"-> {out_path.name}  acc={acc:.1%}")

    print("terminé.")


if __name__ == "__main__":
    main()
