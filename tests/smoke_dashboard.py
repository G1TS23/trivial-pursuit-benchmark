"""Smoke test du dashboard : exécute réellement la page Streamlit (AppTest).

Vérifie que la page se rend sans exception, sans message d'erreur affiché
(gold absent, version de Streamlit trop ancienne...) et avec ses 5 onglets.
Pas besoin d'ouvrir un navigateur. Utilisé par la CI et utilisable à la main :

    python tests/smoke_dashboard.py        (depuis la racine, après `dbt build`)
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

EXPECTED_TABS = 5
APP = Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"

# Console Windows (cp1252) : évite un UnicodeEncodeError sur les accents/emoji.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

at = AppTest.from_file(str(APP), default_timeout=180).run()
problems = [f"exception : {e.value}" for e in at.exception]
problems += [f"erreur affichée : {e.value}" for e in at.error]
if len(at.tabs) != EXPECTED_TABS:
    problems.append(f"{len(at.tabs)} onglet(s) au lieu de {EXPECTED_TABS}")

if problems:
    print("ECHEC du smoke test du dashboard :")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print(f"OK : dashboard rendu sans erreur ({len(at.tabs)} onglets, {len(at.dataframe)} tableaux).")
