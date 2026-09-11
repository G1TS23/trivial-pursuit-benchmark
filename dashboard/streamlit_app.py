"""Étape 3 — Dashboard interactif du benchmark.

Lit la couche GOLD (data/gold/gold.duckdb) EN LECTURE SEULE : dbt doit avoir
tourné avant (`make build`). Ne jamais lancer dbt et Streamlit en même temps
sur le même fichier .duckdb (verrou d'écriture DuckDB).

Lancer :  streamlit run dashboard/streamlit_app.py
"""
from __future__ import annotations

import string
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

GOLD_DB = Path(__file__).resolve().parents[1] / "data" / "gold" / "gold.duckdb"

st.set_page_config(page_title="Benchmark IA — Culture générale", layout="wide")


@st.cache_resource
def con() -> duckdb.DuckDBPyConnection:
    if not GOLD_DB.exists():
        st.error(f"Couche gold introuvable : {GOLD_DB}\nLance `make build` d'abord.")
        st.stop()
    return duckdb.connect(str(GOLD_DB), read_only=True)


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    return con().execute(sql).fetch_df()


fct = q("select * from marts.fct_benchmark_results")

st.title("🎯 Benchmark de modèles d'IA sur des questions de culture générale")
st.caption(f"{len(fct):,} réponses · "
           f"{fct.question_id.nunique():,} questions · "
           f"{fct.model.nunique()} modèles · {fct.prompt_id.nunique()} prompts")

# --- Filtres ---------------------------------------------------------------
with st.sidebar:
    st.header("Filtres")
    models = st.multiselect("Modèles", sorted(fct.model.unique()),
                            default=sorted(fct.model.unique()))
    prompts = st.multiselect("Prompts", sorted(fct.prompt_id.unique()),
                             default=sorted(fct.prompt_id.unique()))
    diffs = st.multiselect("Difficulté", ["easy", "medium", "hard"],
                           default=["easy", "medium", "hard"])
    cats = st.multiselect("Catégories", sorted(fct.category.unique()), default=[])

f = fct[fct.model.isin(models) & fct.prompt_id.isin(prompts) & fct.difficulty.isin(diffs)]
if cats:
    f = f[f.category.isin(cats)]
if f.empty:
    st.warning("Aucune donnée pour ces filtres.")
    st.stop()

# --- KPIs ----------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Précision globale", f"{f.ai_correct.mean():.1%}")
c2.metric("Réponses exploitables", f"{f.is_parsable.mean():.1%}")
c3.metric("Temps médian / question", f"{f.response_time.median():.2f} s")
c4.metric("Meilleur modèle",
          f.groupby("model").ai_correct.mean().idxmax())

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Classement", "Par catégorie", "Par difficulté", "Impact du prompt", "Explorateur d'erreurs"]
)

with tab1:
    lb = (f.groupby(["model", "prompt_id"])
            .agg(precision=("ai_correct", "mean"),
                 exploitables=("is_parsable", "mean"),
                 tps_median=("response_time", "median"),
                 n=("ai_correct", "size"))
            .reset_index()
            .sort_values("precision", ascending=False))
    st.dataframe(lb.style.format({"precision": "{:.1%}", "exploitables": "{:.1%}",
                                  "tps_median": "{:.2f} s"}), use_container_width=True)

    st.subheader("Précision vs latence (frontière de Pareto)")
    pareto = (f.groupby("model")
                .agg(precision=("ai_correct", "mean"),
                     tps_median=("response_time", "median")).reset_index())
    st.altair_chart(
        alt.Chart(pareto).mark_circle(size=200).encode(
            x=alt.X("tps_median", title="Temps médian (s)"),
            y=alt.Y("precision", title="Précision", axis=alt.Axis(format="%")),
            color="model", tooltip=["model", "precision", "tps_median"],
        ).interactive(),
        use_container_width=True,
    )

with tab2:
    by_cat = (f.groupby(["model", "category"]).ai_correct.mean().reset_index())
    n_cat = by_cat["category"].nunique()
    st.altair_chart(
        alt.Chart(by_cat).mark_rect().encode(
            # catégories en lignes (souvent 24, labels longs) : bien plus lisible
            # que 24 colonnes écrasées sur l'axe X.
            y=alt.Y("category:N", title=None,
                    sort=alt.EncodingSortField(field="ai_correct", op="mean", order="descending")),
            x=alt.X("model:N", title=None, axis=alt.Axis(labelAngle=-30)),
            color=alt.Color("ai_correct:Q", title="Précision",
                            scale=alt.Scale(scheme="blues")),
            tooltip=["model", "category", alt.Tooltip("ai_correct", format=".1%")],
        ).properties(height=26 * n_cat + 40),
        use_container_width=True,
    )

with tab3:
    by_diff = (f.assign(random_baseline=1 / f.n_options)
                 .groupby(["model", "difficulty"])
                 .agg(precision=("ai_correct", "mean"),
                      hasard=("random_baseline", "mean")).reset_index())
    order = {"easy": 0, "medium": 1, "hard": 2}
    by_diff["k"] = by_diff.difficulty.map(order)
    st.altair_chart(
        alt.Chart(by_diff.sort_values("k")).mark_bar().encode(
            x=alt.X("difficulty:N", sort=["easy", "medium", "hard"], title=None),
            y=alt.Y("precision:Q", axis=alt.Axis(format="%")),
            color="model:N", xOffset="model:N",
            tooltip=["model", "difficulty", alt.Tooltip("precision", format=".1%"),
                     alt.Tooltip("hasard", format=".1%")],
        ),
        use_container_width=True,
    )
    st.caption("À comparer au taux « au hasard » (1 / nombre d'options).")

with tab4:
    pi = (f.groupby(["model", "prompt_id"])
            .agg(precision=("ai_correct", "mean"),
                 exploitables=("is_parsable", "mean"),
                 longueur=("answer_len", "mean")).reset_index())
    st.altair_chart(
        alt.Chart(pi).mark_bar().encode(
            x=alt.X("prompt_id:N", title=None),
            y=alt.Y("precision:Q", axis=alt.Axis(format="%")),
            color="prompt_id:N", xOffset="model:N",
            column=alt.Column("model:N", title=None),
            tooltip=["model", "prompt_id", alt.Tooltip("precision", format=".1%"),
                     alt.Tooltip("exploitables", format=".1%")],
        ),
        use_container_width=True,
    )
    st.dataframe(pi.style.format({"precision": "{:.1%}", "exploitables": "{:.1%}",
                                 "longueur": "{:.0f}"}), use_container_width=True)

with tab5:
    st.caption(
        "Réponses fausses — **`ai_answer`** est déjà décodé (lettre -> texte de "
        "l'option pour un QCM ; `raw_answer` reste la sortie brute du modèle, "
        "utile pour retrouver le JSON / la lettre d'origine)."
    )

    def fmt_options(opts, correct_letter: str) -> str:
        # `opts` arrive en numpy.ndarray (duckdb -> pandas pour une colonne LIST)
        try:
            if opts is None or len(opts) == 0:
                return ""
        except TypeError:
            return ""
        return "   ".join(
            f"{'✅' if letter == correct_letter else '▫️'} {letter}) {opt}"
            for letter, opt in zip(string.ascii_uppercase, opts)
        )

    err_pool = f[~f.ai_correct].copy()
    if err_pool.empty:
        st.info("Aucune réponse fausse pour ces filtres.")
    else:
        err_pool["options_fmt"] = [
            fmt_options(o, c) for o, c in zip(err_pool["options"], err_pool["correct_letter"])
        ]
        cols = {
            "model": "modèle", "prompt_id": "prompt", "category": "catégorie",
            "difficulty": "difficulté", "question_text": "question",
            "options_fmt": "options (✅ = bonne)", "correct_answer": "bonne réponse",
            "ai_answer": "réponse retenue (décodée)", "raw_answer": "sortie brute",
            "response_time": "temps (s)",
        }
        errs = (err_pool[list(cols)]
                .rename(columns=cols)
                .sample(min(200, len(err_pool)), random_state=0))
        st.dataframe(errs, use_container_width=True, height=500)
