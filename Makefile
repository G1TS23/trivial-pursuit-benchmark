# Pipeline complet : make all
# Python : dbt-core ne supporte pas encore 3.14 -> on cible 3.13.
PYTHON ?= python3.13
VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
DBT    := $(VENV)/bin/dbt

export DBT_PROFILES_DIR := dbt
export DBT_GOLD_DB      := ../data/gold/gold.duckdb
export DBT_SILVER_DIR   := ../data/silver

.PHONY: help venv install hooks scrape clean-silver enrich build test dashboard all clean-data

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Crée le virtualenv
	$(PYTHON) -m venv $(VENV)

install: venv hooks ## Installe les dépendances + packages dbt + hook pre-commit
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	cd dbt && $(abspath $(DBT)) deps

hooks: ## Active le hook pre-commit versionné (.githooks/)
	git config core.hooksPath .githooks
	chmod +x .githooks/*

scrape: ## Étape 1 : scraping OpenTDB -> data/bronze/questions_raw.csv
	$(PY) src/scrape_opentdb.py

clean-silver: ## Étape 2a : nettoyage -> data/silver/questions/
	$(PY) src/clean_silver.py

enrich: ## Étape 2b : réponses des modèles LM Studio -> data/silver/responses/  (ARGS="--limit 20" pour un test)
	$(PY) src/enrich_lmstudio.py $(ARGS)

build: ## Étape 3a : construction de la couche gold avec dbt
	cd dbt && $(abspath $(DBT)) build

test: ## Tests dbt seuls
	cd dbt && $(abspath $(DBT)) test

dashboard: ## Étape 3b : dashboard Streamlit (lecture seule de gold)
	$(VENV)/bin/streamlit run dashboard/streamlit_app.py

all: scrape clean-silver enrich build ## Pipeline complet (hors dashboard)

clean-data: ## Supprime les données générées (bronze/silver/gold)
	rm -rf data/bronze/* data/silver/* data/gold/*
	@touch data/bronze/.gitkeep data/silver/.gitkeep data/gold/.gitkeep
