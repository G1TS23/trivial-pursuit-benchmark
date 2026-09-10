# Trivial poursuite — Benchmark de modèles d'IA sur des questions de culture générale

Projet **M2 DEV — EFREI**. Pipeline complet de data engineering : collecte
(OpenTDB) → enrichissement par un LLM local (LM Studio) → couche métier (dbt +
DuckDB) → dashboard interactif (Streamlit).

> État : **squelette**. Le code d'ingestion / nettoyage / enrichissement et le
> projet dbt sont fonctionnels ; les points de décision d'équipe sont signalés
> par des `TODO` et concentrés dans `config/prompts.yaml` et `.env`.

## 1. Méthodologie

### Architecture en médaillon

| Couche | Contenu | Format | Producteur |
|---|---|---|---|
| **Bronze** | questions brutes du scraping | `data/bronze/questions_raw.csv` | `src/scrape_opentdb.py` |
| **Silver** | questions nettoyées + réponses brutes des modèles | Parquet (`data/silver/`) | `src/clean_silver.py`, `src/enrich_lmstudio.py` |
| **Gold** | données métier (perf modèles, perf prompts…) | `data/gold/gold.duckdb` | **dbt** (`dbt/`) |

Détails et modèle dimensionnel : [`docs/architecture.md`](docs/architecture.md).

### Étape 1 — Scraping OpenTDB

Récupération de **l'intégralité** des questions vérifiées via l'API OpenTDB.
Contraintes gérées : `amount ≤ 50`, **rate limit 1 req/5 s**, **session token**
(anti-doublons ; code 4 = terminé), `encode=base64` (pas d'entités HTML).
Un contrôle de complétude compare le nombre récupéré au comptage annoncé par
`api_count.php` (à reporter dans le rapport).

### Étape 2 — Enrichissement IA (LM Studio)

Pour chaque **question × modèle × prompt actif**, on interroge un modèle servi
par LM Studio et on stocke les colonnes imposées :

- `ai_answer` — réponse du modèle
- `ai_correct` — booléen (réponse == bonne réponse)
- `response_time` — temps de génération en secondes (wall-clock)

\+ `model`, `prompt_id`, `prompt_text`, `run_id`, `raw_answer`, `is_parsable`,
`match_method`, et les stats natives LM Studio (`tokens_per_second`, `ttft`…).

**Prompts** (`config/prompts.yaml`, versionnés) :

| id | mode | idée |
|---|---|---|
| `p1_naif` | open | baseline sans contrainte |
| `p2_format` | mcq_letter | QCM, réponse = 1 lettre (sortie structurée) |
| `p3_role_format` | mcq_letter | + rôle d'expert, interdiction d'expliquer |
| `p4_open_court` | open | réponse ouverte cadrée (désactivé par défaut) |

**Matching `ai_correct`** :
- `mcq_letter` → sortie structurée (`response_format` = enum de lettres) +
  égalité stricte. Ordre des options mélangé de façon déterministe (seed =
  `question_id`) → pas de biais de position.
- `open` → normalisation (casse, accents, articles, ponctuation) + inclusion +
  `rapidfuzz.token_set_ratio ≥ 88`.
- ⚠️ **À valider** : spot-check manuel de 30–50 cas, reporter le taux d'erreur
  du matching dans le rapport.

**Reproductibilité** : `temperature = 0`, `seed` fixe, un seul modèle chargé à
la fois, warm-up non mesuré. Le script est **résumable** (relit
`data/silver/responses/`, ne rejoue que le manquant) → un run interrompu ne perd
rien. Lancer le gros run **le soir**.

### Étape 3 — Couche gold (dbt) + dashboard

`dbt build` construit :
`fct_benchmark_results` (faits) · `dim_question` / `dim_model` / `dim_prompt` ·
`agg_model_leaderboard` · `agg_accuracy_by_category` ·
`agg_accuracy_by_difficulty` (avec écart au hasard) · `agg_prompt_impact`.
Tests dbt : `not_null` / `unique` / `relationships` / `accepted_values`.

Le dashboard Streamlit lit `gold.duckdb` **en lecture seule** : classement,
Pareto précision/latence, heatmap catégorie × modèle, barres par difficulté,
impact du prompt, explorateur d'erreurs.

## 2. Organisation du dépôt

```
config/prompts.yaml        variantes de prompt versionnées
src/scrape_opentdb.py       étape 1  -> bronze
src/clean_silver.py         étape 2a -> silver/questions
src/enrich_lmstudio.py      étape 2b -> silver/responses (resumable)
src/common.py               chemins, question_id, normalisation
dbt/                        projet dbt-duckdb (staging + marts + tests)
dashboard/streamlit_app.py  rapport interactif
docs/architecture.md        schéma médaillon + modèle dimensionnel
data/{bronze,silver,gold}/  data lake (gitignoré)
.githooks/pre-commit        garde-fou anti data lake / secrets / gros fichiers
Makefile                    orchestration : make all
```

## 3. Setup complet

### Pré-requis

- **Python 3.13** (`brew install python@3.13`) — `dbt-core` ne supporte pas
  encore 3.14. Adapter `PYTHON` dans le `Makefile` si besoin.
- **LM Studio** — https://lmstudio.ai
- CLI `lms` : `npx lmstudio install-cli` (ou via l'app, onglet Developer).

### Installation

```bash
git clone <url> && cd trivial-pursuit-benchmark
cp .env.example .env          # ajuster MODELS
make install                  # venv + pip + dbt deps + hook pre-commit
```

`make install` active le **hook pre-commit** versionné (`.githooks/`, via
`core.hooksPath`) : il bloque un commit qui contiendrait des données du data
lake, un `.env`, un artefact généré (`*.duckdb`, `*.parquet`, `dbt/target/`) ou
un fichier > 5 Mo, vérifie `git diff --check` et compile les `.py` stagés
(+ `ruff` si présent). Contournement ponctuel : `git commit --no-verify`.
Pour l'activer seul : `make hooks`.

### Modèles LM Studio

```bash
lms get qwen2.5-3b-instruct
lms get gemma-2-2b-it
lms get llama-3.2-3b-instruct
lms server start              # sert l'API sur http://localhost:1234
lms ls                        # copier les clés exactes dans .env (MODELS=...)
```

> Choisir des modèles **petits et rapides** (2–3B). Budget : ~4 500 questions ×
> 3 modèles × 3 prompts ≈ 40 k appels ≈ plusieurs heures → lancer `make enrich`
> le soir. Noter la **quantization** (`Q4_K_M`…) pour `dim_model`.

### Exécution

```bash
make scrape        # étape 1  (~10-15 min, rate limit OpenTDB)
make clean-silver  # étape 2a
make enrich        # étape 2b (long ; resumable — relancer si coupé)
make build         # étape 3a : dbt build (gold + tests)
make dashboard     # étape 3b : Streamlit
```

`make all` enchaîne scrape → clean-silver → enrich → build.

> ⚠️ Ne pas lancer `make build` et `make dashboard` en même temps : DuckDB
> n'autorise qu'un seul processus en écriture sur `gold.duckdb`.

### Alternative au SDK `lmstudio`

LM Studio expose aussi une API **OpenAI-compatible** sur
`http://localhost:1234/v1`. Pour l'utiliser, remplacer la classe `LMStudio` de
`src/enrich_lmstudio.py` par un client `openai` (`base_url=...`, `api_key="lm-studio"`)
et lire `response_time` au wall-clock.

### Dépannage réseau (proxy EFREI / Cato)

Le réseau EFREI passe par un proxy **Cato Networks** qui (a) inspecte le TLS et
(b) **bloque `opentdb.com`** (catégorie « Games ») — HTTP 403 avec une page
« Corporate Internet policy violation ».

- **Inspection TLS** (`CERTIFICATE_VERIFY_FAILED`, « Cato Networks Root CA ») :
  `truststore` (dans `requirements.txt`) fait utiliser le magasin de l'OS — il
  suffit d'installer « Cato Networks Root CA » comme approuvé dans Trousseau
  d'accès (Accès au trousseau → Système). Sinon, bundle CA maison :
  ```bash
  mkdir -p certs
  # récupère le dernier certificat de la chaîne (la racine Cato) :
  openssl s_client -showcerts -connect opentdb.com:443 -servername opentdb.com </dev/null 2>/dev/null \
    | awk '/BEGIN CERTIFICATE/{i++} i{print > "certs/c" i ".pem"}'
  cat "$(.venv/bin/python -c 'import certifi;print(certifi.where())')" certs/c3.pem > certs/ca-bundle.pem
  export REQUESTS_CA_BUNDLE="$PWD/certs/ca-bundle.pem"   # requests le lit automatiquement
  ```
  `certs/` est gitignoré (spécifique au poste). En dernier recours :
  `python src/scrape_opentdb.py --insecure`.
- **Blocage du domaine** : le code ne peut rien y faire. Lancer `make scrape`
  depuis un **réseau non filtré** (partage de connexion mobile, réseau perso, ou
  Cato Client en pause s'il est installé sur le poste), puis **committer
  `data/bronze/questions_raw.csv`** (exception ajoutée au `.gitignore`) pour ne
  plus dépendre du réseau ensuite. Les étapes 2 et 3 sont 100 % locales.

## 4. Livrables

1. Architecture de projet complète — ce dépôt.
2. Ce `README.md` (méthodologie, organisation, setup).
3. Application Streamlit — `dashboard/streamlit_app.py`.

## 5. Points de décision d'équipe (TODO)

- [ ] Liste finale des modèles (`.env`) et quantizations.
- [ ] Prompts actifs (`config/prompts.yaml`) — arbitrer budget temps vs finesse d'analyse.
- [ ] Méthode `ai_correct` de référence + spot-check chiffré à mettre dans le rapport.
- [ ] Seed / dataset complet ou échantillon stratifié si le temps manque.
- [ ] `dim_model` : ajouter un seed `seeds/model_meta.csv` (params, quantization, famille).
- [ ] Rédaction du rapport d'analyse (page Streamlit dédiée ou section README).
