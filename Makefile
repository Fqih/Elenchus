# Elenchus — top-level convenience commands.
#
# Backend (Python / FastAPI / Studio) and frontend (React / Vite) are
# sibling trees; this Makefile is a thin facade so you don't have to
# `cd` into each one.
#
# Usage:
#   make help         — list every target with a one-liner
#   make install      — pip install backend + Phase 7 optional deps
#   make test         — run pytest on all three test roots
#   make smoke        — walk the Phase 5 smoke test end-to-end
#   make smoke7       — walk the Phase 7 smoke test end-to-end
#   make serve        — start the FastAPI server on :8765
#   make fe-install   — npm ci in studio/frontend
#   make fe-test      — vitest in studio/frontend
#   make fe-typecheck — tsc --noEmit in studio/frontend
#   make fe-dev       — vite dev server on :5173 (needs backend on :8765)
#   make fe-build     — vite build to studio/frontend/dist
#   make dev          — run backend + frontend together
#   make ci           — what GitHub Actions runs (test + fe-test + fe-typecheck)

# ---- Backend knobs ----

PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
PYTEST       ?= $(PYTHON) -m pytest
PORT         ?= 8765
DB           ?= /tmp/studio.sqlite
FRONTEND_DIR := studio/frontend

# Loads the shared NLI lib path; some envs need it for sentence-transformers.
export LD_LIBRARY_PATH ?= $(HOME)/.local/lib

.DEFAULT_GOAL := help

.PHONY: help
help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):.*## /\1###/' | \
	  awk 'BEGIN {FS = "###"} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---- Backend ----

.PHONY: install
install: ## pip install backend with Phase 7 deps (falls back if Loopward/Lethe absent)
	$(PIP) install -e ".[dev,studio,phase7]" \
	  || { echo "::warning::Phase 7 install failed — retrying without phase7"; \
	       $(PIP) install -e ".[dev,studio]"; }

.PHONY: install-base
install-base: ## pip install backend without Phase 7 (CI without vendored deps)
	$(PIP) install -e ".[dev,studio]"

.PHONY: test
test: ## run pytest (covers tests/, benchmark/tests/, studio/tests/)
	$(PYTEST) -q

.PHONY: test-studio
test-studio: ## run pytest on studio/ only
	$(PYTEST) studio/tests -q

.PHONY: serve
serve: ## start FastAPI server on :8765
	$(PYTHON) -m studio.api.server --db $(DB) --port $(PORT)

.PHONY: smoke
smoke: ## Phase 5 E2E smoke test (boots the real server, walks the full flow)
	$(PYTHON) -m studio.examples.studio_smoke_test

.PHONY: smoke7
smoke7: ## Phase 7 E2E smoke test (Soteria retry + Lethe memory)
	$(PYTHON) -m studio.examples.studio_phase7_smoke_test

.PHONY: benchmark
benchmark: ## regenerate RAGTruth benchmark numbers (see benchmark/RESULTS.md)
	$(PYTHON) -m benchmark.prepare_dataset
	$(PYTHON) -m benchmark.run_benchmark --n 200 --seeds 1 2 3 --pool-size 5000

# ---- Frontend ----

.PHONY: fe-install
fe-install: ## npm ci in studio/frontend
	cd $(FRONTEND_DIR) && npm ci

.PHONY: fe-test
fe-test: ## vitest in studio/frontend
	cd $(FRONTEND_DIR) && npm test -- --run

.PHONY: fe-typecheck
fe-typecheck: ## tsc --noEmit in studio/frontend
	cd $(FRONTEND_DIR) && npm run typecheck

.PHONY: fe-build
fe-build: ## vite build to studio/frontend/dist
	cd $(FRONTEND_DIR) && npm run build

.PHONY: fe-dev
fe-dev: ## vite dev server on :5173 (needs backend on :8765)
	cd $(FRONTEND_DIR) && npm run dev

.PHONY: fe-clean
fe-clean: ## remove studio/frontend/node_modules and dist
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist

# ---- Combined ----

# Run backend + frontend together. Backend binds :8765; frontend binds :5173.
# Ctrl-C kills both. Output is interleaved with [api] / [frontend] tags.
.PHONY: dev
dev: ## run backend (:8765) and frontend (:5173) together
	@trap 'kill 0' INT TERM EXIT; \
	( $(MAKE) serve 2>&1 | sed 's/^/[api] /' & ) ; \
	( $(MAKE) fe-dev 2>&1 | sed 's/^/[frontend] /' & ) ; \
	wait

.PHONY: ci
ci: test fe-typecheck fe-test ## the full local CI gate (pytest + frontend typecheck + vitest)

.PHONY: clean
clean: fe-clean ## remove build artifacts
	rm -rf elenchus.egg-info .pytest_cache **/__pycache__ */**/__pycache__
	find . -name '*.pyc' -delete

# ---- Docker ----

.PHONY: docker-build
docker-build: ## docker build -t elenchus:dev (builds frontend too)
	ELENCHUS_API_TOKEN=$${ELENCHUS_API_TOKEN:-devsecret} \
	  docker build -f Dockerfile.backend -t elenchus:dev .

.PHONY: docker-up
docker-up: ## docker compose up with a default API token (for local dev)
	ELENCHUS_API_TOKEN=$${ELENCHUS_API_TOKEN:-devsecret} \
	  docker compose up --build

.PHONY: docker-down
docker-down: ## docker compose down (keeps the volume)
	docker compose down
