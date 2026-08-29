# VR Image Sorter — local setup / run (macOS + Linux)
# Windows: use  .\make.cmd <target>  (same target names, see make.ps1)

SHELL := /bin/bash
PY    ?= python3
VENV  := backend/.venv
PYBIN := $(VENV)/bin/python

# uv installs the Python deps in seconds instead of minutes. Fall back to pip.
UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  MKVENV  = uv venv $(VENV) --python $(PY)
  INSTALL = VIRTUAL_ENV=$(VENV) uv pip install -r backend/requirements.txt
else
  MKVENV  = $(PY) -m venv $(VENV)
  INSTALL = $(VENV)/bin/pip install --upgrade pip && $(VENV)/bin/pip install -r backend/requirements.txt
endif

# npm ci is reproducible and much faster than npm install when the lockfile matches.
NPM_INSTALL = npm ci --prefer-offline --no-audit --fund=false || npm install --no-audit --fund=false

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        up down logs build rebuild test bench clean dist doctor sort resume watch apply

help: ## Show this help
	@echo "make <target>   (Windows: .\\make.cmd <target>)"
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

doctor: ## Check prerequisites are installed
	@echo "python : $$($(PY) --version 2>&1)"
	@echo "uv     : $${UV:-$$(command -v uv || echo 'not found (pip fallback, slower)')}"
	@echo "node   : $$(node -v 2>/dev/null || echo 'NOT FOUND')"
	@echo "npm    : $$(npm -v 2>/dev/null || echo 'NOT FOUND')"
	@echo "docker : $$(docker --version 2>/dev/null || echo 'not found (only needed for make up)')"

## ---------- native (no Docker) ----------

setup: setup-backend setup-frontend ## One-shot install: backend venv + OCR models + frontend deps
	@echo ""
	@echo "Setup complete. Run 'make dev' then open http://localhost:8080"

setup-backend: ## Backend venv + Python deps + pre-downloaded OCR models
	$(MKVENV)
	$(INSTALL)
	cd backend && ../$(VENV)/bin/python preload_models.py

setup-frontend: ## Frontend deps
	$(NPM_INSTALL)

dev: ## Run backend + frontend together (Ctrl-C stops both)
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## Backend only on :8000
	cd backend && ../$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend: ## Frontend only on :8080
	VITE_API_URL=http://localhost:8000 npm run dev -- --port 8080

## ---------- docker ----------

up: ## Build + start full stack (frontend :8080, backend :8000)
	docker compose up --build -d
	@echo "frontend http://localhost:8080   backend http://localhost:8000/docs"

down: ## Stop stack
	docker compose down

logs: ## Tail stack logs
	docker compose logs -f

build: ## Build images without starting
	docker compose build

rebuild: ## Force full rebuild, no cache
	docker compose build --no-cache

## ---------- bulk folder processing ----------
# The browser cannot hold 100k File objects and preview blobs; these read from
# disk instead, record progress per image, and resume after an interruption.

sort: ## Sort a folder: make sort IN=./photos OUT=./sorted
	@test -n "$(IN)" -a -n "$(OUT)" || { echo "usage: make sort IN=./photos OUT=./sorted"; exit 2; }
	cd backend && OMP_NUM_THREADS=1 ../$(VENV)/bin/python cli.py sort --input "$(abspath $(IN))" --output "$(abspath $(OUT))" $(SORT_ARGS)

resume: ## Continue an interrupted sort: make resume IN=./photos OUT=./sorted
	@test -n "$(IN)" -a -n "$(OUT)" || { echo "usage: make resume IN=./photos OUT=./sorted"; exit 2; }
	cd backend && OMP_NUM_THREADS=1 ../$(VENV)/bin/python cli.py sort --input "$(abspath $(IN))" --output "$(abspath $(OUT))" --resume $(SORT_ARGS)

watch: ## Process images as they land: make watch IN=./dropbox OUT=./sorted
	@test -n "$(IN)" -a -n "$(OUT)" || { echo "usage: make watch IN=./dropbox OUT=./sorted"; exit 2; }
	cd backend && OMP_NUM_THREADS=1 ../$(VENV)/bin/python cli.py watch --input "$(abspath $(IN))" --output "$(abspath $(OUT))" $(SORT_ARGS)

apply: ## Apply corrected codes: make apply OUT=./sorted
	@test -n "$(OUT)" || { echo "usage: make apply OUT=./sorted"; exit 2; }
	cd backend && ../$(VENV)/bin/python cli.py apply --csv "$(abspath $(OUT))/review.csv" --output "$(abspath $(OUT))"

## ---------- checks ----------

test: ## Accuracy check against ./input (known VR codes)
	$(PYBIN) test_pipeline.py

bench: ## Timing on ./input
	@cd backend && ../$(VENV)/bin/python -c "import sys,glob,time; sys.path.insert(0,'.'); \
from scanner.pipeline import process_pipeline as p; \
fs=sorted(glob.glob('../input/*')); t=time.monotonic(); r=[p(open(f,'rb').read()) for f in fs]; \
d=time.monotonic()-t; print(f'{len(fs)} imgs {d:.1f}s  {d/len(fs):.2f}s/img  hits={sum(1 for x in r if x)}/{len(fs)}')"

## ---------- packaging ----------

dist: ## Build a distributable zip of the WORKING TREE in ./dist
	@mkdir -p dist
	@rm -f dist/vr-image-sorter.zip
	@# Working tree, not HEAD: git archive would silently ship the last commit
	@# and drop any uncommitted fix. Tracked + untracked, minus gitignored.
	@{ git ls-files; git ls-files --others --exclude-standard; } | sort -u \
	  | grep -v '^dist/' | zip -q -@ dist/vr-image-sorter.zip
	@echo "wrote $(PWD)/dist/vr-image-sorter.zip ($$(du -h dist/vr-image-sorter.zip | cut -f1), $$(unzip -l dist/vr-image-sorter.zip | tail -1 | awk '{print $$2}') files)"

clean: ## Remove venv, node_modules, build output
	rm -rf $(VENV) node_modules dist
