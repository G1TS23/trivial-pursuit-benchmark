"""Étape 1 — Scraping OpenTDB -> couche BRONZE (data/bronze/questions_raw.csv).

Récupère l'INTÉGRALITÉ des questions vérifiées d'OpenTDB.

Contraintes de l'API (https://opentdb.com/api_config.php) gérées ici :
  - amount max = 50 par requête
  - rate limit = 1 requête / 5 s par IP  (code 5 -> backoff)
  - session token pour éviter les doublons (code 4 = token vidé = terminé)
  - encode=base64 : évite les entités HTML, on décode en UTF-8 propre
  - codes réponse : 0 ok / 1 pas assez / 2 param invalide / 3 token inconnu
                    / 4 token vide / 5 rate limit

Sortie : CSV brut, une ligne = une question. Aucune transformation métier
(le nettoyage se fait en couche silver).
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

from common import BRONZE_CSV, ensure_dirs, question_id

# Réseaux à inspection TLS (proxy d'entreprise/école) : utiliser le magasin de
# certificats de l'OS si `truststore` est installé. Sans effet ailleurs.
try:  # pragma: no cover
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

API = "https://opentdb.com"
REQUEST_PAUSE = 5.0          # respect strict du rate limit
AMOUNT = 50
TIMEOUT = 30

CSV_FIELDS = [
    "question_id", "category", "type", "difficulty",
    "question", "correct_answer", "incorrect_answers", "scraped_at",
]


def _b64(s: str) -> str:
    return base64.b64decode(s).decode("utf-8")


class BlockedError(RuntimeError):
    """Le réseau (proxy/filtrage) refuse l'accès à OpenTDB."""


def _json(r: requests.Response) -> dict:
    """r.json() avec un message clair si le proxy renvoie une page de blocage."""
    body_lower = r.text.lower()
    if "cato" in body_lower or "policy violation" in body_lower:
        raise BlockedError(
            "OpenTDB est bloqué par le proxy réseau (Cato Networks / filtrage "
            "'Games'). Rien à corriger dans le code : lance le scraping depuis "
            "un réseau non filtré (partage de connexion mobile, réseau perso, "
            "Cato Client en pause) ou fais débloquer opentdb.com.\n"
            f"  HTTP {r.status_code} — {r.text[:200].replace(chr(10), ' ')}"
        )
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "application/json" not in ctype:
        raise BlockedError(
            f"réponse non-JSON (HTTP {r.status_code}, {ctype}) : "
            f"{r.text[:200].replace(chr(10), ' ')}"
        )
    return r.json()


def get_token(session: requests.Session) -> str:
    r = session.get(f"{API}/api_token.php", params={"command": "request"}, timeout=TIMEOUT)
    return _json(r)["token"]


def list_categories(session: requests.Session) -> list[dict]:
    r = session.get(f"{API}/api_category.php", timeout=TIMEOUT)
    return _json(r)["trivia_categories"]


def category_count(session: requests.Session, cat_id: int) -> int:
    r = session.get(f"{API}/api_count.php", params={"category": cat_id}, timeout=TIMEOUT)
    return _json(r)["category_question_count"]["total_question_count"]


def fetch_batch(session: requests.Session, token: str, category: int | None) -> tuple[int, list[dict]]:
    params = {"amount": AMOUNT, "encode": "base64", "token": token}
    if category is not None:
        params["category"] = category
    for attempt in range(6):
        r = session.get(f"{API}/api.php", params=params, timeout=TIMEOUT)
        payload = _json(r)
        code = payload["response_code"]
        if code == 5:                       # rate limit -> backoff
            wait = REQUEST_PAUSE * (attempt + 2)
            print(f"  [rate limit] pause {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            continue
        return code, payload.get("results", [])
    raise RuntimeError("rate limit persistant après 6 tentatives")


def parse_row(raw: dict) -> dict:
    question = _b64(raw["question"])
    correct = _b64(raw["correct_answer"])
    incorrect = [_b64(x) for x in raw["incorrect_answers"]]
    return {
        "question_id": question_id(question, correct),
        "category": _b64(raw["category"]),
        "type": _b64(raw["type"]),
        "difficulty": _b64(raw["difficulty"]),
        "question": question,
        "correct_answer": correct,
        "incorrect_answers": json.dumps(incorrect, ensure_ascii=False),
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit-categories", type=int, default=None,
                    help="Ne scraper que les N premières catégories (tests).")
    ap.add_argument("--out", default=str(BRONZE_CSV))
    ap.add_argument("--ca-bundle", default=os.environ.get("REQUESTS_CA_BUNDLE"),
                    help="Bundle CA personnalisé (réseau à inspection TLS).")
    ap.add_argument("--insecure", action="store_true",
                    help="Désactive la vérification TLS (dépannage — non recommandé).")
    args = ap.parse_args()

    ensure_dirs()
    session = requests.Session()
    session.headers["User-Agent"] = "EFREI-M2-DEV-benchmark/1.0"
    if args.insecure:
        session.verify = False
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
        print("[!] vérification TLS désactivée (--insecure)", file=sys.stderr)
    elif args.ca_bundle:
        session.verify = args.ca_bundle

    try:
        token = get_token(session)
    except BlockedError as exc:
        sys.exit(f"\n[scraping impossible] {exc}\n")
    print(f"token = {token}")
    cats = list_categories(session)
    if args.limit_categories:
        cats = cats[: args.limit_categories]

    seen: set[str] = set()
    rows: list[dict] = []
    expected_total = 0

    for i, cat in enumerate(cats, 1):
        cid, cname = cat["id"], cat["name"]
        want = category_count(session, cid)
        expected_total += want
        print(f"[{i}/{len(cats)}] {cname} (id={cid}) ~ {want} questions")
        time.sleep(REQUEST_PAUSE)
        got = 0
        while True:
            code, results = fetch_batch(session, token, cid)
            if code == 4:            # token vidé pour cette requête -> catégorie finie
                break
            if code == 1:            # plus assez de questions
                break
            if code in (2, 3):
                raise RuntimeError(f"réponse API code {code} sur catégorie {cid}")
            for raw in results:
                row = parse_row(raw)
                if row["question_id"] in seen:
                    continue
                seen.add(row["question_id"])
                rows.append(row)
                got += 1
            time.sleep(REQUEST_PAUSE)
        print(f"    -> {got} questions récupérées")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    # --- contrôle de complétude (à reporter dans le README) ---
    print("-" * 60)
    print(f"écrit          : {args.out}")
    print(f"questions       : {len(rows)}")
    print(f"attendu (API)   : ~{expected_total}")
    print(f"écart           : {expected_total - len(rows)} "
          "(doublons inter-catégories + questions retirées entre les 2 appels)")


if __name__ == "__main__":
    main()
