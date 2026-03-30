# Convenience targets for local development (run from backend/).
#
#   make install      # venv + deps + editable backend package
#   make test
#   make api          # uvicorn with reload
#   make openapi      # write openapi.json (no server)
#   make gen-client [OUT=../frontend/src/api]
#   make ingest [ARGS=...]   # e.g. make ingest ARGS="--once 10"
#   make migrate      # alembic upgrade head

MAKEFILE_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
export PYTHONPATH := $(abspath $(MAKEFILE_DIR)/..)

# Default output for generated TS client (sibling repo layout: finance-tracker/frontend/…)
OUT ?= ../frontend/src/api

VENV         := $(MAKEFILE_DIR)/.venv
PYTHON       := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
.PHONY: help install test api openapi gen-client ingest migrate shell

help:
	@echo "Finance Tracker backend — common commands"
	@echo ""
	@echo "  make install              Create .venv if missing; pip install deps + editable package"
	@echo "  make test                 Run pytest"
	@echo "  make api                  Run FastAPI (http://0.0.0.0:8000)"
	@echo "  make openapi              Export OpenAPI to openapi.json"
	@echo "  make gen-client [OUT=…]   Generate TS Axios client (default OUT=$(OUT); needs Node npx; frontend needs axios)"
	@echo "  make ingest [ARGS=…]      Run CLI ingest (default incremental Gmail; pass ARGS for --once, --offline, …)"
	@echo "  make migrate              alembic upgrade head"
	@echo "  make shell                PYTHONPATH set; print venv python path"

$(PYTHON):
	@test -d "$(VENV)" || (command -v python3 >/dev/null 2>&1 && python3 -m venv "$(VENV)" || python -m venv "$(VENV)")
	@"$(PYTHON)" -m pip install -U pip

install: $(PYTHON)
	@"$(PIP)" install -r "$(MAKEFILE_DIR)/requirements.txt"
	@"$(PIP)" install -e "$(MAKEFILE_DIR)"

test: $(PYTHON)
	@"$(PYTHON)" -m pytest $(ARGS)

api: $(PYTHON)
	@"$(PYTHON)" -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

openapi: $(PYTHON)
	@"$(PYTHON)" "$(MAKEFILE_DIR)/scripts/export_openapi.py" "$(MAKEFILE_DIR)/openapi.json"

gen-client: $(PYTHON)
	@bash "$(MAKEFILE_DIR)/scripts/generate_ts_client.sh" "$(OUT)"

ingest: $(PYTHON)
	@cd "$(MAKEFILE_DIR)" && "$(PYTHON)" -m backend.cli ingest $(ARGS)

migrate: $(PYTHON)
	@cd "$(MAKEFILE_DIR)" && "$(PYTHON)" -m alembic upgrade head

shell:
	@echo "PYTHONPATH=$(PYTHONPATH)"
	@echo "PYTHON=$(PYTHON)"
