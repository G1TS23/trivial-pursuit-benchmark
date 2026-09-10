# Architecture

## Pipeline de bout en bout

```
                 OpenTDB API
                     │  src/scrape_opentdb.py  (token, rate-limit 5s, base64)
                     ▼
┌─────────────────────────────────────────┐
│ BRONZE   data/bronze/questions_raw.csv   │  brut, immuable, horodaté
└─────────────────────────────────────────┘
                     │  src/clean_silver.py    (dédup, types, QCM déterministe)
                     ▼
┌─────────────────────────────────────────┐
│ SILVER   data/silver/questions/*.parquet │  observations propres
│          data/silver/responses/          │  réponses brutes des modèles
│            model=<m>/prompt=<p>/*.parquet │  (resumable, partitionné)
└─────────────────────────────────────────┘
                     ▲  src/enrich_lmstudio.py (LM Studio, temp=0, seed)
                     │
                 LM Studio  (serveur local :1234, modèles GGUF)
                     │
                     │  dbt build  (dbt-duckdb)
                     ▼
┌─────────────────────────────────────────┐
│ GOLD     data/gold/gold.duckdb           │  1 table = 1 question métier
│   staging.stg_questions / stg_responses   │
│   marts.fct_benchmark_results (faits)     │
│   marts.dim_question / dim_model / dim_prompt
│   marts.agg_model_leaderboard            │
│   marts.agg_accuracy_by_category         │
│   marts.agg_accuracy_by_difficulty       │
│   marts.agg_prompt_impact               │
└─────────────────────────────────────────┘
                     │  lecture seule
                     ▼
             Streamlit dashboard
```

## Modèle dimensionnel (couche gold)

**Fait** `fct_benchmark_results` — grain : une réponse = `(question_id, model, prompt_id, run_id)`

| colonne | rôle |
|---|---|
| `result_key` | clé de substitution (surrogate key) |
| `question_id`, `model`, `prompt_id` | clés vers les dimensions |
| `ai_correct` | mesure booléenne principale |
| `is_parsable` | la sortie du modèle était-elle exploitable |
| `response_time`, `gen_time_sec`, `ttft_sec`, `tokens_per_second` | mesures de latence |
| `answer_len`, `category`, `difficulty`, `n_options` | axes dénormalisés (perf) |

**Dimensions** : `dim_question` (texte, bonne réponse, `random_baseline = 1/n_options`), `dim_model`, `dim_prompt`.

## Choix structurants

- **QCM déterministe** : l'ordre des options est mélangé avec un seed dérivé du `question_id` → stable entre runs, pas de biais de position, et `ai_correct` = égalité stricte de lettre (fiable).
- **Sortie structurée LM Studio** (`response_format` = enum de lettres) pour les prompts `mcq_letter` → matching sans ambiguïté.
- **Mode `open`** (prompt naïf) : matching par normalisation + `rapidfuzz` (seuil 88) → sert l'axe « connaissance vs reconnaissance ».
- **Résumable** : `enrich_lmstudio.py` relit `data/silver/responses/` et ne rejoue que les triplets manquants.
- **Verrou DuckDB** : dbt écrit `gold.duckdb`, Streamlit l'ouvre en `read_only`. Jamais les deux en écriture.
