# Trivial poursuite - M2 DEV

<aside>

**Date :** 10, 11 et 30 septembre 2026
**Format du rendu :** Projet Github
**En groupes de 3**

</aside>

# Objectif

Votre mission est de concevoir un **rapport de benchmark** évaluant les performances d’un ou plusieurs modèles d’IA sur des questions de culture générale.

L’exercice permet de mettre en œuvre un **pipeline complet** de data ingénierie :

- collecte et intégration de données,
- enrichissement par appel à des modèles d’IA,
- génération et visualisation de résultats.

# Étape 1 : Constitution d’un dataset de questions de culture générale

1. **Source de données** :
    - Utilisez le site Open Trivia Database (OpenTDB), une API publique proposant des milliers de questions catégorisées (science, histoire, divertissement, etc.).
    - Vous devez scraper ces données pour récupérer l’intégralité du dataset proposé.

# Étape 2 : Module de data intégration & enrichissement avec un modèle d’IA

1. **Intégration de l’IA** :
    - Installez Ollama ou LMStudio (des runtime légers permettant d’exécuter localement des modèles LLM).
    - Téléchargez un modèle adapté à votre machine (par exemple `llama`, `gemma`, ou tout autre modèle supporté).
    - Utilisez l’**API Python** de l’outil ****pour automatiser la génération de réponses IA :
    - Pour chaque question de votre dataset, interrogez le modèle et stockez la réponse générée.
2. **Enrichissement du dataset** :
    - Ajoutez les colonnes suivantes :
        - `ai_answer` : réponse donnée par le modèle
        - `ai_correct` : booléen (`True` si la réponse IA correspond à la bonne réponse)
        - `response_time` : temps de génération mesuré en secondes

## Importance du prompt

Le **prompt** (la façon dont vous posez la question au modèle) influence fortement la qualité des réponses obtenues.

- Une même question peut donner des résultats très différents selon le contexte fourni.
- Exemple :
    - Prompt simple : *"Qui a peint la Joconde ?"*
    - Prompt plus robuste : *"Réponds uniquement par un nom propre. Question : Qui a peint la Joconde ?"*
    - Il existe des versions **encore plus optimisées**, à vous de les trouver !
- Dans ce cas pratique, il est recommandé de **standardiser les prompts** pour que le benchmark soit cohérent.
- Vous pouvez tester plusieurs variantes de prompt afin d’observer leur impact sur :
    - le **taux de bonnes réponses**,
    - la **longueur et précision** des réponses,
    - la **robustesse** face aux ambiguïtés.

Pour un benchmark rigoureux, vous pouvez garder une trace de la formulation du prompt dans votre dataset.

# Étape 3 : Rapport de benchmark

Vous allez produire un **rapport d’analyse des résultats** afin de comparer les performances du modèle.

### Analyses possibles

Ces axes d’analyse sont des exemples, vous pouvez vous en inspirer ou trouver les vôtres :

- **Performance globale** : taux de bonnes réponses (%)
- **Par catégorie** : précision par thème (histoire, sciences, etc.)
- **Par niveau de difficulté** : facile vs difficile
- **Par temps de réponse** : rapidité moyenne par question
- **Comparaison de modèles** : exécutez le benchmark avec plusieurs modèles disponibles et comparez leurs performances.
- **Analyses exploratoires supplémentaires** : identifiez et proposez d’autres axes d’analyse pertinents à partir des données
- Etc.

# Méthodologie

Vous devez mettre en place une architecture en médaillon pour stocker les données de ce projet.

**Architecture attendue :**

- Couche bronze : Données brutes issues du scraping : `questions_raw.csv`
- Couche silver : Données pré-traitées (nettoyage, normalisation, etc.) +  réponses brutes du/des modèles `en parquet`
    - Silver contient des observations propres et exploitables
- Couche gold : Données métiers (performance des modèles, performance des prompts, etc.) `format duckdb`
    - Gold répond directement à une question métier

**Ingénierie des données attendue :**

- Utilisation de dbt pour construire la couche gold

**Visualisation des résultats du benchmark :**

- Utilisez **Streamlit** pour produire un dashboard interactif des résultats du benchmark

# Livrables attendus

**Un dépôt Github contenant :**

1. Votre architecture de projet complète
2. Un README.md expliquant votre méthodologie, votre organisation de projet et le setup complet
3. Une **application Streamlit** pour un rapport interactif