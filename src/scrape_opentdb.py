"""Étape 1 — Scraping OpenTDB -> couche BRONZE (data/bronze/questions_raw.csv).

Récupère l'INTÉGRALITÉ des questions vérifiées d'OpenTDB.

Doc API : https://opentdb.com/api_config.php
  - `amount` max = 50 par requête ; 1 seule catégorie par appel (ou aucune)
  - **rate limit = 1 requête / 5 s par IP, TOUS endpoints confondus** (code 5)
    -> ici un throttle central garantit >= 5 s entre chaque requête HTTP
  - session token : `api_token.php?command=request`, puis `&token=...` sur
    `api.php`. Le token empêche les doublons ; quand la base est épuisée pour
    la requête -> code 4 (fin). (`command=reset` remettrait le token à zéro,
    inutile pour un pull complet unique.)
  - `encode=base64` : on décode en UTF-8 propre (pas d'entités HTML)
  - codes réponse : 0 ok / 1 pas assez / 2 param invalide / 3 token inconnu
                    / 4 token vide (fin) / 5 rate limit

Mode par défaut : **flux unique** (un token, sans paramètre `category`, on
boucle jusqu'au code 4). C'est ce que recommande la doc pour tout récupérer,
avec le minimum de requêtes. `--by-category` : variante catégorie par catégorie
(plus de requêtes, permet un contrôle de complétude par thème).

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
REQUEST_PAUSE = 5.2          # marge au-dessus de la limite officielle (5 s)
AMOUNT = 50
TIMEOUT = 30
MAX_RETRIES = 6

CSV_FIELDS = [
    "question_id", "category", "type", "difficulty",
    "question", "correct_answer", "incorrect_answers", "scraped_at",
]


class BlockedError(RuntimeError):
    """Le réseau (proxy/filtrage) refuse l'accès à OpenTDB."""


def _b64(s: str) -> str:
    return base64.b64decode(s).decode("utf-8")


class Client:
    """Session HTTP avec throttle global (>= REQUEST_PAUSE entre 2 requêtes)."""

    def __init__(self, verify: bool | str = True):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "EFREI-M2-DEV-benchmark/1.0"
        self.s.verify = verify
        self._last = 0.0

    def get_json(self, path: str, **params) -> dict:
        wait = REQUEST_PAUSE - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.s.get(f"{API}/{path}", params=params or None, timeout=TIMEOUT)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(REQUEST_PAUSE * (attempt + 1))
                continue
            finally:
                self._last = time.monotonic()

            body_lc = r.text[:2000].lower()
            if "cato" in body_lc or "policy violation" in body_lc:
                raise BlockedError(
                    "OpenTDB est bloqué par le proxy réseau (Cato Networks / "
                    "filtrage 'Games'). Rien à corriger dans le code : lance le "
                    "scraping depuis un réseau non filtré (partage de connexion "
                    "mobile, réseau perso, Cato Client en pause) ou fais "
                    "débloquer opentdb.com.\n"
                    f"  HTTP {r.status_code} — {r.text[:200].replace(chr(10), ' ')}"
                )
            if r.status_code == 429:
                time.sleep(REQUEST_PAUSE * (attempt + 2))
                self._last = time.monotonic()
                continue
            r.raise_for_status()
            if "application/json" not in r.headers.get("content-type", ""):
                raise BlockedError(
                    f"réponse non-JSON (HTTP {r.status_code}) : "
                    f"{r.text[:200].replace(chr(10), ' ')}"
                )
            return r.json()
        raise RuntimeError(f"échec réseau persistant sur {path}: {last_exc}")


# --- endpoints ----------------------------------------------------------
def get_token(c: Client) -> str:
    return c.get_json("api_token.php", command="request")["token"]


def list_categories(c: Client) -> list[dict]:
    return c.get_json("api_category.php")["trivia_categories"]


def global_verified_count(c: Client) -> int:
    data = c.get_json("api_count_global.php")
    return int(data["overall"]["total_num_of_verified_questions"])


def fetch_batch(c: Client, token: str, category: int | None) -> tuple[int, list[dict]]:
    params = {"amount": AMOUNT, "encode": "base64", "token": token}
    if category is not None:
        params["category"] = category
    for attempt in range(MAX_RETRIES):
        payload = c.get_json("api.php", **params)
        code = payload["response_code"]
        if code == 5:                       # rate limit -> backoff supplémentaire
            wait = REQUEST_PAUSE * (attempt + 2)
            print(f"  [code 5 / rate limit] pause {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            continue
        return code, payload.get("results", [])
    raise RuntimeError("code 5 persistant après plusieurs tentatives")


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


def collect(c: Client, token: str, category: int | None, seen: set[str],
            rows: list[dict], cap: int | None) -> int:
    got = 0
    while True:
        code, results = fetch_batch(c, token, category)
        if code in (1, 4):                   # plus de questions pour cette requête
            return got
        if code == 3:                        # token expiré (6 h) -> on en reprend un
            token = get_token(c)
            continue
        if code == 2:
            raise RuntimeError(f"code 2 (paramètre invalide) — category={category}")
        for raw in results:
            row = parse_row(raw)
            if row["question_id"] in seen:
                continue
            seen.add(row["question_id"])
            rows.append(row)
            got += 1
            if cap and len(rows) >= cap:
                return got


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by-category", action="store_true",
                    help="Boucle catégorie par catégorie (au lieu du flux unique).")
    ap.add_argument("--max-questions", type=int, default=None,
                    help="Plafond (smoke test).")
    ap.add_argument("--out", default=str(BRONZE_CSV))
    ap.add_argument("--ca-bundle", default=os.environ.get("REQUESTS_CA_BUNDLE"),
                    help="Bundle CA personnalisé (réseau à inspection TLS).")
    ap.add_argument("--insecure", action="store_true",
                    help="Désactive la vérification TLS (dépannage — non recommandé).")
    args = ap.parse_args()

    ensure_dirs()
    verify: bool | str = True
    if args.insecure:
        verify = False
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
        print("[!] vérification TLS désactivée (--insecure)", file=sys.stderr)
    elif args.ca_bundle:
        verify = args.ca_bundle
    c = Client(verify=verify)

    try:
        t0 = time.monotonic()
        token = get_token(c)
        print(f"token = {token}")

        seen: set[str] = set()
        rows: list[dict] = []

        if args.by_category:
            for i, cat in enumerate(list_categories(c), 1):
                cid, cname = cat["id"], cat["name"]
                n = collect(c, token, cid, seen, rows, args.max_questions)
                print(f"[{i:2}] {cname:<35} +{n}")
                if args.max_questions and len(rows) >= args.max_questions:
                    break
        else:
            print("mode flux unique (toutes catégories)…")
            while True:
                before = len(rows)
                collect(c, token, None, seen, rows, args.max_questions)
                print(f"  {len(rows)} questions cumulées")
                if len(rows) == before:      # code 4 : plus rien
                    break
                if args.max_questions and len(rows) >= args.max_questions:
                    break

        try:
            expected = global_verified_count(c)
        except Exception:                    # noqa: BLE001
            expected = None
    except BlockedError as exc:
        sys.exit(f"\n[scraping impossible] {exc}\n")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    dt = time.monotonic() - t0
    print("-" * 60)
    print(f"écrit           : {args.out}")
    print(f"questions       : {len(rows)}   (en {dt / 60:.1f} min)")
    if expected is not None:
        print(f"vérifiées (API) : {expected}")
        print(f"couverture      : {len(rows) / expected:.1%}")


if __name__ == "__main__":
    main()
