# VR Image Sorter — local setup / run (macOS + Linux)
# Windows: use  .\make.cmd <target>  (same target names, see make.ps1)

SHELL := /bin/bash
PY    ?= python3
VENV  := backend/.venv
PYBIN := $(VENV)/bin/python

# uv installs the Python deps in seconds instead of minutes. Fall back to pip.
UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  MKVENV  = uv venv $(VENV) --python $(PY) --allow-existing
  INSTALL = VIRTUAL_ENV=$(VENV) uv pip install -r backend/requirements.txt
else
  MKVENV  = test -x $(PYBIN) || $(PY) -m venv $(VENV)
  INSTALL = $(VENV)/bin/pip install --upgrade pip && $(VENV)/bin/pip install -r backend/requirements.txt
endif

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend build-frontend dev dev-backend dev-frontend dev-all \
        up down logs build rebuild test test-real bench-varahi test-all bench clean dist doctor sort resume watch apply

help: ## Show this help
	@echo "make <target>   (Windows: .\\make.cmd <target>)"
	@echo ""
	@echo "--- ZERO-NPM MODE (Python Only) ---"
	@grep -hE '^[a-zA-Z_-]+:.*?## (Python|One-shot|Run unified|Timing|Accuracy|Master|Sort|Continue|Process|Apply)' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "--- FRONTEND DEV MODE (with npm) ---"
	@grep -hE '^[a-zA-Z_-]+:.*?## (Optional|Build React)' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

doctor: ## Check prerequisites are installed (Python required, others optional)
	@echo "python : $$($(PY) --version 2>&1)"
	@echo "uv     : $${UV:-$$(command -v uv || echo 'not found (pip fallback, slower)')}"
	@echo "node   : $$(node -v 2>/dev/null || echo 'NOT FOUND (optional)')"
	@echo "npm    : $$(npm -v 2>/dev/null || echo 'NOT FOUND (optional)')"
	@echo "docker : $$(docker --version 2>/dev/null || echo 'not found (only needed for make up)')"

## ---------- ZERO-NPM MODE (Python Only) ----------

setup: setup-backend ## One-shot install: backend venv + OCR models (no npm needed)
	@echo ""
	@echo "Setup complete! Run 'make dev' then open http://localhost:8000"

setup-backend: ## Python venv + deps + pre-downloaded OCR models
	$(MKVENV)
	$(INSTALL)
	cd backend && ../$(VENV)/bin/python preload_models.py

dev: ## Run unified full stack on http://localhost:8000 (no npm needed)
	@python3 -c "import webbrowser, time; time.sleep(1); webbrowser.open('http://localhost:8000')" 2>/dev/null &
	cd backend && APP_ENV=development ../$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

dev-backend: ## Backend only on :8000 (same as dev)
	cd backend && APP_ENV=development ../$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

## ---------- FRONTEND DEV MODE (with npm) ----------

setup-frontend: ## Optional: install npm packages and rebuild frontend
	npm ci --prefer-offline --no-audit --fund=false || npm install --no-audit --fund=false
	npm run build
	mkdir -p backend/static && cp -r dist/* backend/static/

build-frontend: ## Build React app with Vite and sync to backend/static
	npm run build
	mkdir -p backend/static && cp -r dist/* backend/static/

dev-frontend: ## Optional: Vite HMR frontend server on :8080 (if editing React src/)
	VITE_API_URL=http://localhost:8000 npm run dev -- --port 8080

dev-all: ## Optional: Run backend :8000 + Vite HMR :8080 simultaneously
	@$(MAKE) -j2 dev-backend dev-frontend

## ---------- docker ----------

up: ## Build + start full stack (frontend :${UI_PORT:-8088}, backend :${PORT:-8001})
	docker compose up --build -d
	@echo "frontend http://localhost:$${UI_PORT:-8088}   backend http://localhost:$${PORT:-8001}/docs"

down: ## Stop stack
	docker compose down

logs: ## Tail stack logs
	docker compose logs -f

build: ## Build images without starting
	docker compose build

rebuild: ## Force full rebuild, no cache
	docker compose build --no-cache

## ---------- bulk folder processing ----------

sort: ## Sort a folder: make sort IN=./photos OUT=./sorted
	@test -n "$(IN)" -a -n "$(OUT)" || { echo "usage: make sort IN=./photos OUT=./sorted"; exit 2; }
	cd backend && OMP_NUM_THREADS=1 ../$(VENV)/bin/python cli.py sort --input "$(abspath $(IN))" --output "$(abspath $(OUT))" $(SORT_ARGS)

resume: ## Continue interrupted sort: make resume IN=./photos OUT=./sorted
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

test-real: ## Accuracy check against sandbox real images
	cd backend && ../$(VENV)/bin/python test_real_images.py

bench-varahi: ## 100-image benchmark on Varahi production saree dataset
	cd backend && ../$(VENV)/bin/python test_varahi_benchmark.py

test-all: ## Master benchmark across all 124+ images in all datasets
	cd backend && APP_ENV=development ../$(VENV)/bin/python test_all_datasets.py

bench: ## Timing benchmark on ./input
	cd backend && APP_ENV=development ../$(VENV)/bin/python bench.py

## ---------- packaging ----------

dist: ## Build a distributable zip of the WORKING TREE in ./dist
	@mkdir -p dist
	@rm -f dist/vr-image-sorter.zip
	@{ git ls-files; git ls-files --others --exclude-standard; } | sort -u \
	  | grep -v '^dist/' | zip -q -@ dist/vr-image-sorter.zip
	@echo "wrote $(PWD)/dist/vr-image-sorter.zip ($$(du -h dist/vr-image-sorter.zip | cut -f1), $$(unzip -l dist/vr-image-sorter.zip | tail -1 | awk '{print $$2}') files)"

clean: ## Remove venv, node_modules, dist
	rm -rf $(VENV) node_modules dist
