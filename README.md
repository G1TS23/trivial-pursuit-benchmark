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

- [x] Liste finale des modèles (`.env`) : `qwen2.5-3b-instruct`, `gemma-2-2b-it`,
      `llama-3.2-3b-instruct`, `phi-3.5-mini-instruct`.
- [x] Prompts actifs (`config/prompts.yaml`) : `p1_naif` (open), `p2_format` et
      `p3_role_format` (QCM structuré).
- [x] Méthode `ai_correct` de référence : lettre stricte (sortie structurée) pour
      `p2_format`/`p3_role_format` ; fuzzy/inclusion pour `p1_naif` — voir limites en §6.
- [x] Échantillon stratifié : `SAMPLE_PER_CAT=75` → 1784 questions (~70/catégorie),
      figé (`--question-ids-from`) pour rester comparable entre les 2 runs.
- [x] `dim_model` enrichie via seed `dbt/seeds/model_meta.csv` (famille, éditeur,
      taille, contexte, quantization, poids du GGUF).
- [x] Rapport §6 complet : classement, impact du prompt, par catégorie/difficulté,
      spot-check manuel, conclusion générale + limites.

## 6. Résultats — run du 10-11/09/2026 (+ extension du 11/09)

**Config** : 1784 questions (échantillon stratifié, ~70/catégorie, 24 catégories) ×
**4 modèles** × **3 prompts** = 21 408 réponses. `temperature=0`, seed fixe.
Le 4ᵉ modèle (`phi-3.5-mini-instruct`) et le 3ᵉ prompt (`p3_role_format`) ont
été ajoutés dans un 2ᵉ run, restreint explicitement (`--question-ids-from`) aux
**mêmes 1784 questions** que le run initial pour rester comparable.

### Classement (`marts.agg_model_leaderboard`)

| modèle | prompt | précision | temps médian |
|---|---|---:|---:|
| llama-3.2-3b-instruct | `p2_format` (QCM) | **67,6 %** | 0,37 s |
| gemma-2-2b-it | `p2_format` | 66,6 % | 0,54 s |
| gemma-2-2b-it | `p3_role_format` (QCM + rôle) | 66,4 % | 0,55 s |
| llama-3.2-3b-instruct | `p3_role_format` | 64,9 % | 0,70 s |
| qwen2.5-3b-instruct | `p2_format` | 64,4 % | 0,45 s |
| phi-3.5-mini-instruct | `p2_format` | 63,4 % | 0,62 s |
| qwen2.5-3b-instruct | `p3_role_format` | 62,9 % | 0,61 s |
| phi-3.5-mini-instruct | `p3_role_format` | 60,2 % | 0,28 s |
| gemma-2-2b-it | `p1_naif` (ouvert) | 43,4 % | 1,26 s |
| llama-3.2-3b-instruct | `p1_naif` | 39,2 % | 0,82 s |
| phi-3.5-mini-instruct | `p1_naif` | 35,4 % | 1,85 s |
| qwen2.5-3b-instruct | `p1_naif` | 35,2 % | 1,18 s |

**Constat n°1 — le prompt contraint domine largement.** Pour les 4 modèles,
`p2_format`/`p3_role_format` battent `p1_naif` de **+20 à +30 points**, et
répondent 1,5 à 6× plus vite (sortie JSON courte vs prose libre). C'est la
comparaison de prompts demandée par le sujet, et elle tranche nettement.

**Constat n°2 — le prompt « plus élaboré » n'est pas le plus efficace, contrairement à l'intuition.**
Le sujet invite à chercher des prompts « encore plus optimisés » (§ Importance
du prompt) ; on a donc ajouté `p3_role_format` (rôle d'expert + interdiction
explicite d'expliquer) en plus de `p2_format` (QCM simple, sans rôle). Résultat :
**`p3_role_format` est *moins* précis que `p2_format` pour les 4 modèles sans
exception** (-0,2 à -3,1 points selon le modèle — moyenne -1,9 pt). Ajouter du
contexte et des consignes supplémentaires n'a pas amélioré la justesse ici ;
l'hypothèse la plus probable est que la contrainte de sortie structurée
(l'enum de lettres) fait déjà tout le travail utile du "format prompt", et que
le rôle ajouté n'apporte rien à un modèle 2-4B sur un simple QCM — il ajoute
seulement des tokens de contexte. Sur le temps de réponse, l'effet est mixte :
`phi-3.5-mini-instruct` est nettement plus rapide en `p3` (0,28 s vs 0,62 s),
`llama-3.2-3b-instruct` nettement plus lent (0,70 s vs 0,37 s) — pas de
tendance unique. **`p2_format` reste donc le meilleur prompt trouvé dans ce
benchmark**, ce qui est en soi une réponse (négative mais rigoureuse) au défi
du sujet.

**Constat n°3 — classement des modèles (moyenne `p2_format`+`p3_role_format`,
les 2 prompts au matching fiable)** :

| modèle | précision moyenne | temps moyen |
|---|---:|---:|
| gemma-2-2b-it | **66,5 %** | 0,55 s |
| llama-3.2-3b-instruct | 66,3 % | 0,53 s |
| qwen2.5-3b-instruct | 63,7 % | 0,53 s |
| phi-3.5-mini-instruct | 61,8 % | 0,45 s |

Les 4 modèles restent proches (5,5 points d'écart). `gemma-2-2b-it`
(2B, quantization Q5_K_M — voir la limite plus bas) et `llama-3.2-3b-instruct`
(3B, Q4_K_M) se disputent la tête ; `phi-3.5-mini-instruct` est le plus rapide
en moyenne mais aussi le moins précis, et son mode `p1_naif` a nécessité un
repli sans sortie structurée (erreur HTTP 500 "peg-native format" sur ce
build LM Studio pour ce modèle — géré automatiquement, voir `enrich_lmstudio.py`).

**Constat n°4 — llama-3.2-3b est le plus précis en QCM mais pas le plus verbeux
en ouvert**, gemma-2-2b est meilleur en réponse libre (43,4 % vs 35-39 %) —
suggère une meilleure capacité à produire une réponse ouverte exploitable,
indépendamment de la « connaissance » brute mesurée en QCM.

### Limite méthodologique du matching en mode `p1_naif` (important)

Le prompt `p1_naif` n'impose **aucun format** (`{question}` brut). Sur les
questions `boolean` en particulier, les modèles répondent souvent en prose
sans jamais écrire littéralement `True`/`False`, ce que le matcher (fuzzy +
inclusion textuelle) ne peut pas reconnaître. Sur les 3251 réponses `p1_naif`
comptées fausses, **772 (23,7 %) portent sur des questions `boolean`**, et
parmi elles, **36 % contiennent un indice explicite d'accord/désaccord**
cohérent avec la bonne réponse (`"That's correct!"`, `"is not accurate"`,
`"This is a myth"`...) sans jamais énoncer le mot attendu. Exemples :

| question | bonne réponse | début de la réponse du modèle | verdict matching |
|---|---|---|---|
| *DHCP stands for Dynamic Host Configuration Port.* | False | *"It seems there is a small typo... DHCP actually stands for Dynamic Host Configuration **Protocol**, not Port."* | ❌ faux (aucun `False` littéral) |
| *Psychology is the science of behavior and mind.* | True | *"**That's correct!** Psychology indeed focuses on..."* | ❌ faux (jamais `True`) |
| *Type 1 diabetes is a result of the liver working improperly.* | False | *"Type 1 diabetes is **not caused by** the liver working improperly. Instead, it is an autoimmune..."* | ❌ faux (jamais `False`) |

**Conclusion à retenir pour le rapport** : le score `p1_naif` (35-43 %) est un
**plancher**, pas la vraie compétence des modèles sur ces questions — il mesure
surtout leur capacité à *formater* une réponse exploitable, pas seulement à la
connaître. C'est précisément pourquoi `p2_format` (réponse contrainte à une
lettre, via sortie structurée) est la mesure de référence du benchmark, et
`p1_naif` sert de démonstration du problème plutôt que de score comparable.

### Par difficulté (score de référence `p2_format`, 4 modèles)

| difficulté | précision moyenne | hasard | écart au hasard |
|---|---:|---:|---:|
| easy | 72,4 % | 30,1 % | +42,3 pts |
| medium | 63,1 % | 28,6 % | +34,5 pts |
| hard | 60,0 % | 27,4 % | +32,6 pts |

La précision baisse logiquement avec la difficulté (-12 pts entre easy et
hard), mais **l'écart au hasard reste élevé même sur les questions `hard`**
(+32,6 pts) : les modèles ne s'effondrent pas vers le niveau du hasard, ils
gardent un vrai signal de connaissance sur les questions difficiles — le label
de difficulté d'OpenTDB (fixé par les contributeurs) ne les met pas en échec
autant qu'on pourrait le craindre pour des modèles 2-4B.

### Par catégorie (score de référence `p2_format`, moyenne des 4 modèles)

| catégories les plus fortes | précision | catégories les plus faibles | précision |
|---|---:|---|---:|
| Art | 86,8 % | Entertainment: Japanese Anime & Manga | 46,4 % |
| Mythology | 82,7 % | Entertainment: Video Games | 47,1 % |
| Science & Nature | 82,4 % | Entertainment: Board Games | 49,7 % |
| History | 79,0 % | Entertainment: Cartoon & Animations | 53,8 % |
| General Knowledge | 75,6 % | Entertainment: Television | 54,0 % |

**Écart de ~40 points entre la meilleure catégorie (Art) et la pire (Anime &
Manga).** Le clivage est net et cohérent, inchangé par l'ajout du 4ᵉ modèle :
les modèles excellent sur la **culture encyclopédique classique** (art,
mythologie, sciences, histoire — probablement sur-représentée dans leurs
données d'entraînement, avec des faits stables et peu ambigus) et échouent sur
la **culture pop-geek de niche** (mécaniques précises de jeux vidéo, intrigues
d'anime, règles de jeux de plateau — faits très spécifiques, changeants, peu
documentés en texte généraliste).

**Divergence entre modèles** la plus marquée : *Celebrities* (llama 66 % /
gemma 64 % / phi-3.5 55 % / qwen 47 %, écart 19 pts) et *Cartoon & Animations*
(écart 18 pts). `llama-3.2-3b-instruct` reste systématiquement en tête sur les
catégories où les modèles divergent le plus ; `phi-3.5-mini-instruct` prend
l'avantage sur *Animals* (76 % contre 61-63 %) et `qwen2.5-3b-instruct` reste
seul en tête sur *Science: Mathematics* (73 % contre 63-64 %) — piste :
entraînement renforcé sur les mathématiques, documenté par l'éditeur de Qwen2.5.

### Spot-check manuel (fiabilité du score de référence `p2_format`)

**Méthode** : échantillon aléatoire reproductible (`seed=42`), 30 réponses
`p2_format` — 15 tirées parmi les `ai_correct=True`, 15 parmi les
`ai_correct=False` (stratifié pour couvrir les deux sens d'erreur possibles).
Pour chaque ligne, vérification manuelle que (a) la `correct_answer` d'OpenTDB
est factuellement exacte et (b) le verdict `ai_correct` reflète bien la
comparaison lettre choisie / lettre attendue.

**Résultat** : **30/30 verdicts confirmés corrects (100 %)** ; 2 questions trop
pointues pour être vérifiées avec certitude (mème 4chan « 404 Girl », détail de
dialogue *Gravity Falls*) mais sans anomalie détectée. **0 erreur de matching.**
Cohérent avec le mécanisme : `p2_format` compare une lettre unique issue d'une
sortie JSON contrainte à la lettre pré-calculée en silver (0 incohérence
lettre/option détectée sur les 5248 questions, cf. `clean_silver.py`) — pas de
place pour l'ambiguïté observée en mode `p1_naif` ci-dessus.

**Conclusion méthodologique** : le score `p2_format` (64-68 % selon le modèle)
est fiable et sert de métrique de référence du rapport ; `p1_naif` doit être
présenté comme un score plancher illustrant l'effet du prompt, pas comme une
mesure de connaissance comparable.

### Conclusion générale

1. **Le prompt change tout** : +20 à +30 points de précision en imposant un
   format de réponse plutôt qu'en laissant le modèle répondre librement
   (`p1_naif`) — à budget de calcul égal, la variable la plus rentable n'est
   pas le choix du modèle mais celui du prompt.
2. **« Plus élaboré » n'est pas « meilleur »** : en réponse directe au défi du
   sujet (chercher un prompt « encore plus optimisé »), `p3_role_format`
   (rôle d'expert + consignes renforcées) fait systématiquement **moins bien**
   que le `p2_format` plus simple, pour les 4 modèles (-0,2 à -3,1 pts). La
   contrainte de sortie structurée suffisait déjà ; ajouter du contexte n'a
   rien apporté ici.
3. **Les 4 modèles sont proches sur le score de référence** (61,8-66,5 % de
   moyenne QCM), `gemma-2-2b-it` et `llama-3.2-3b-instruct` en tête, mais
   **divergent fortement par catégorie** (jusqu'à 19 pts d'écart sur
   *Celebrities*) — un classement global masque des profils de force différents.
4. **La connaissance encyclopédique classique tient, la pop-culture de niche
   s'effondre** : ~40 pts d'écart entre *Art* (86,8 %) et *Entertainment:
   Japanese Anime & Manga* (46,4 %). Attendu pour des modèles 2-4B dont
   l'entraînement sur-représente probablement les corpus généralistes.
5. **La difficulté annotée par OpenTDB dégrade la précision mais pas le signal
   de connaissance** : même sur `hard`, l'écart au hasard reste de +32,6 pts.
6. **Le score de référence est fiable** (spot-check 30/30) ; le score du
   prompt naïf, lui, ne l'est pas et ne doit pas être comparé sans réserve.

**Limites** :
- La comparaison de modèles n'est pas à quantization égale — `gemma-2-2b-it`
  tourne en `Q5_K_M` quand les 3 autres sont en `Q4_K_M`/`Q4_K_S` (voir
  `dbt/seeds/model_meta.csv`). Une quantization plus fine peut partiellement
  expliquer pourquoi gemma, le plus petit modèle (2B), reste compétitif.
- `phi-3.5-mini-instruct` n'a **jamais réussi la sortie structurée** sur ce
  build LM Studio (0/1784 réponses JSON valides sur `p2_format` et
  `p3_role_format` — HTTP 400 "Failed to initialize samplers" à chaque appel) ;
  le repli automatique vers texte libre + extraction par regex a pris le
  relais (`enrich_lmstudio.py`). Ses scores QCM reposent donc sur un mécanisme
  différent des 3 autres modèles — moins garanti, quoique vérifié à 100 %
  exploitable (`parsable_rate=1.0`). Un autre build LM Studio pourrait changer
  ce résultat spécifique.
