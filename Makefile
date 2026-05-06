.DEFAULT_GOAL := help

SETUP_DIR := setup
UNAME_S   := $(shell uname -s)
UNAME_M   := $(shell uname -m)
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_FILE  ?= .env

# Defaults for the gunicorn invocation; override on the command line, e.g.
#   make run WORKERS=10 BIND=0.0.0.0:9000 CERTFILE= KEYFILE=
WORKERS  ?= 5
BIND     ?= 0.0.0.0:8081
CERTFILE ?= cert.pem
KEYFILE  ?= key.pem

# Self-signed cert defaults; override on the command line, e.g.
#   make certs CERT_DAYS=730 CERT_SUBJECT=/CN=arctos.example.com
CERT_DAYS    ?= 365
CERT_SUBJECT ?= /CN=localhost

.PHONY: help \
        all \
        setup setup-os setup-macos setup-ubuntu setup-python install setup-frontend \
        lint format \
        test unit integration \
        run dev frontend certs \
        db-baseline db-migrate db-revision db-current db-history \
        db-backup db-check-duplicates

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ── Setup ─────────────────────────────────────────────────────────────────────

all: setup install setup-frontend ## Run full setup: system deps, python deps, and frontend tools

setup: setup-os ## Auto-detect OS and run the appropriate system setup

setup-os:
ifeq ($(UNAME_S),Darwin)
	@$(MAKE) --no-print-directory setup-macos
else ifeq ($(UNAME_S),Linux)
	@$(MAKE) --no-print-directory setup-ubuntu
else
	@echo "Unsupported OS: $(UNAME_S). Only macOS and Linux (Ubuntu) are supported."; exit 1
endif

setup-macos: ## Install macOS system dependencies (Homebrew, Xcode CLI, packages, Python)
	@chmod +x $(SETUP_DIR)/setup-macos.sh
	@$(SETUP_DIR)/setup-macos.sh

setup-ubuntu: ## Install Ubuntu system dependencies (apt packages, uv, Python)
	@chmod +x $(SETUP_DIR)/setup-ubuntu.sh
	@$(SETUP_DIR)/setup-ubuntu.sh

setup-python: ## Install the project's Python toolchain via uv
	@chmod +x $(SETUP_DIR)/setup-python.sh
	@$(SETUP_DIR)/setup-python.sh

install: ## Sync Python dependencies and install pre-commit hooks
	@uv sync
	@uv run pre-commit install

setup-frontend: ## Install the Dioxus CLI required to build/serve the frontend
	@cargo install dioxus-cli

# ── Lint & Format ─────────────────────────────────────────────────────────────

lint: ## Run ruff
	@uv run ruff check .

format: ## Auto-format code with ruff
	@uv run ruff format .

# ── Test ──────────────────────────────────────────────────────────────────────

test: ## Run all tests (extra pytest args via ARGS=..., e.g. make test ARGS="-k foo")
	@uv run pytest tests/ $(ARGS)

unit: ## Run unit tests only (extra pytest args via ARGS=...)
	@uv run pytest tests/ -m unit $(ARGS)

integration: ## Run integration tests only (extra pytest args via ARGS=...)
	@uv run pytest tests/ -m integration $(ARGS)

# ── Run ───────────────────────────────────────────────────────────────────────

run: ## Run the backend with gunicorn (loads $(ENV_FILE) if present)
	@uv sync
	@if [ ! -f "$(ENV_FILE)" ]; then \
		echo "warning: $(ENV_FILE) not found; continuing with current environment only"; \
	fi
	@set -a; \
	[ -f "$(ENV_FILE)" ] && . "./$(ENV_FILE)"; \
	set +a; \
	PYTHONPATH="$(REPO_ROOT):$$PYTHONPATH" \
	uv run gunicorn \
		--workers=$(WORKERS) \
		--bind $(BIND) \
		--log-level debug \
		$(if $(strip $(CERTFILE)),--certfile=$(CERTFILE)) \
		$(if $(strip $(KEYFILE)),--keyfile=$(KEYFILE)) \
		run_app:app

dev: ## Run the backend for local dev (HTTP on :5006, no TLS)
	@$(MAKE) --no-print-directory run ARCTOS_CORS_DEV=1 BIND=0.0.0.0:5006 CERTFILE= KEYFILE=

frontend: ## Serve the Dioxus frontend
	@cd frontend && dx serve

# ── Database migrations ───────────────────────────────────────────────────────
#
# All targets shell out to alembic via `uv run` so the project-pinned version
# is always used. See `migrations/README.md` for the full workflow.
# Run `make db-backup` BEFORE every db-migrate.

db-baseline: ## One-shot: stamp an existing database at the current alembic head
	@uv run alembic stamp head

db-migrate: ## Apply all outstanding migrations (run `make db-backup` first!)
	@uv run alembic upgrade head

db-revision: ## Autogenerate a migration; usage: make db-revision MSG="snake_case_message"
	@if [ -z "$(MSG)" ]; then \
		echo "error: pass MSG=... e.g. make db-revision MSG=\"add_unique_player_email\""; \
		exit 1; \
	fi
	@uv run alembic revision --autogenerate -m "$(MSG)"

db-current: ## Print the revision currently applied to the database
	@uv run alembic current

db-history: ## Print the full alembic revision history
	@uv run alembic history

db-backup: ## Snapshot the live SQLite database to backups/ (run BEFORE every db-migrate)
	@chmod +x scripts/backup_db.sh
	@scripts/backup_db.sh

db-check-duplicates: ## Report rows that violate would-be-unique column groups
	@uv run python scripts/check_duplicates.py

# ── Misc ──────────────────────────────────────────────────────────────────────

certs: ## Generate self-signed SSL certs at $(CERTFILE)/$(KEYFILE) (use FORCE=1 to overwrite)
	@if [ -z "$(FORCE)" ] && { [ -f "$(CERTFILE)" ] || [ -f "$(KEYFILE)" ]; }; then \
		echo "refusing to overwrite existing $(CERTFILE) / $(KEYFILE); pass FORCE=1 to regenerate"; \
		exit 1; \
	fi
	@command -v openssl >/dev/null || { echo "openssl not found in PATH"; exit 1; }
	@openssl req -x509 -newkey rsa:4096 \
		-keyout "$(KEYFILE)" -out "$(CERTFILE)" \
		-sha256 -days $(CERT_DAYS) -nodes \
		-subj "$(CERT_SUBJECT)"
	@chmod 600 "$(KEYFILE)"
	@echo "Generated $(CERTFILE) and $(KEYFILE) (valid $(CERT_DAYS) days, subject $(CERT_SUBJECT))"
