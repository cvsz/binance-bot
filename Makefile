# Binance Spot Trading Bot — developer & operator commands
#   make            -> list targets
#   make setup      -> venv + deps + config files (first time)
#   make check      -> lint + tests (run before every commit)
# Override variables on the command line, e.g.  make backtest DAYS=180  |  make status MODE=live

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

# ---- variables ---------------------------------------------------------------
PYTHON   ?= python3
VENV     ?= .venv
PY       := $(VENV)/bin/python
PIP      := $(PY) -m pip
CONFIG   ?= config.yaml
MODE     ?= paper
DAYS     ?= 90
CSV      ?=
OUT      ?= reports
HOST     ?= 127.0.0.1
PORT     ?= 8080
ARGS     ?=
SESSION  ?= binance-bot-$(MODE)
BACKUP_DIR ?= backups
COMPOSE  ?= docker compose
IMAGE    ?= binance-bot:local
STAMP    := $(VENV)/.installed
RUN      := $(PY) run.py -c $(CONFIG)
VERBOSE_FLAG := $(if $(filter 1 yes true,$(VERBOSE)),-v,)

# ---- help --------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@awk 'BEGIN{FS=":.*## "} /^##@/{printf "\n\033[1m%s\033[0m\n", substr($$0,5)} \
	    /^[a-zA-Z0-9_.-]+:.*## /{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nVariables: MODE=$(MODE) CONFIG=$(CONFIG) DAYS=$(DAYS) HOST=$(HOST) PORT=$(PORT) VERBOSE=$(VERBOSE)\n"

##@ Setup
$(STAMP): requirements.txt requirements-dev.txt constraints.txt
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements-dev.txt -c constraints.txt
	@touch $@

.PHONY: install
install: $(STAMP) ## Create .venv and install pinned deps (re-runs only when requirements change)

.PHONY: config
config: ## Create config.yaml / .env from the examples if missing (never overwrites)
	@if [ ! -f $(CONFIG) ]; then cp config.example.yaml $(CONFIG); echo "created $(CONFIG)"; else echo "$(CONFIG) exists, kept"; fi
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env"; else echo ".env exists, kept"; fi
	@chmod 600 .env
	@mkdir -p data

.PHONY: setup
setup: install config perms ## First-time setup: install + config + permissions
	@echo "setup done -> next: make backtest"

.PHONY: perms
perms: ## Lock down file permissions (.env 600, project dir 755)
	@chmod 755 .
	@[ ! -f .env ] || chmod 600 .env
	@[ ! -f $(CONFIG) ] || chmod 644 $(CONFIG)
	@stat -c '  %a %n' . $$(ls -d .env $(CONFIG) 2>/dev/null)

.PHONY: lock
lock: $(STAMP) ## Re-pin constraints.txt from the venv (only after `make check` passes)
	$(MAKE) check
	@{ echo "# Exact versions the test-suite passed with (pip install -r requirements.txt -c constraints.txt)."; \
	   echo "# Regenerate: make lock"; $(PIP) freeze --exclude-editable; } > constraints.txt
	@echo "constraints.txt updated"

.PHONY: doctor
doctor: ## Diagnose environment: python, venv, config, secrets (names only), docker
	@echo "python : $$($(PYTHON) --version 2>&1)"
	@if [ -x $(PY) ]; then echo "venv   : $$($(PY) --version) ($(VENV))"; else echo "venv   : MISSING -> make install"; fi
	@if [ -f $(CONFIG) ]; then \
	    $(PY) -c "from bot.config import load_config; c=load_config('$(CONFIG)'); \
print(f'config : OK {c.symbol} {c.timeframe} strategy={c.strategy} testnet={c.testnet}')" \
	    || echo "config : INVALID"; else echo "config : MISSING -> make config"; fi
	@if [ -f .env ]; then \
	    echo ".env   : perms $$(stat -c %a .env)$$([ "$$(stat -c %a .env)" = 600 ] || echo '  <- run: make perms')"; \
	    for k in BINANCE_TESTNET_API_KEY BINANCE_API_KEY TELEGRAM_BOT_TOKEN DASHBOARD_TOKEN BOT_CONFIRM_REAL_MONEY; do \
	        v=$$( { grep -E "^$$k=" .env || true; } | head -1 | cut -d= -f2-); \
	        printf '         %-26s %s\n' "$$k" "$$( [ -n "$$v" ] && echo set || echo empty)"; done; \
	else echo ".env   : MISSING -> make config"; fi
	@if command -v docker >/dev/null; then echo "docker : $$(docker --version)"; else echo "docker : not installed"; fi
	@if command -v tmux >/dev/null; then echo "tmux   : $$(tmux -V)"; else echo "tmux   : not installed (needed for start/stop)"; fi

##@ Quality
.PHONY: test
test: $(STAMP) ## Run the test-suite (ARGS="-k name" to filter)
	$(PY) -m pytest $(ARGS)

.PHONY: test-fast
test-fast: $(STAMP) ## Tests without the slow simulations, stop at first failure
	$(PY) -m pytest -x -m "not slow" $(ARGS)

.PHONY: lint
lint: $(STAMP) ## Ruff lint
	$(PY) -m ruff check .

.PHONY: fix
fix: $(STAMP) ## Ruff auto-fix safe lint issues
	$(PY) -m ruff check --fix .

.PHONY: fmt-check
fmt-check: $(STAMP) ## Show formatting differences (does not modify files)
	$(PY) -m ruff format --check --diff . || true

.PHONY: check
check: lint test ## Lint + tests (gate before commit/merge)
	@echo "check: PASS"

##@ Trading
.PHONY: backtest
backtest: $(STAMP) ## Backtest (DAYS=90 | CSV=file.csv, OUT=reports, VERBOSE=1)
	$(RUN) $(VERBOSE_FLAG) backtest $(if $(CSV),--csv $(CSV),--days $(DAYS)) --out $(OUT)

.PHONY: paper
paper: $(STAMP) ## Paper trading in the foreground (live prices, simulated money)
	$(RUN) $(VERBOSE_FLAG) paper

.PHONY: live
live: $(STAMP) ## Live trading; Binance TESTNET when exchange.testnet: true
	$(RUN) $(VERBOSE_FLAG) live

.PHONY: live-real
live-real: $(STAMP) ## REAL MONEY. Requires CONFIRM=YES_I_ACCEPT_THE_RISK plus the .env gate
	@if [ "$(CONFIRM)" != "YES_I_ACCEPT_THE_RISK" ]; then \
	    echo "refusing: run  make live-real CONFIRM=YES_I_ACCEPT_THE_RISK  (and set BOT_CONFIRM_REAL_MONEY in .env)"; exit 2; fi
	$(RUN) $(VERBOSE_FLAG) live --real-money

.PHONY: status
status: $(STAMP) ## Position, risk state, recent trades (MODE=paper|live)
	$(RUN) status --mode $(MODE)

.PHONY: health
health: $(STAMP) ## Exit 0 if the bot heartbeat is fresh (MODE=paper|live)
	$(RUN) health --mode $(MODE)

.PHONY: resume
resume: $(STAMP) ## Clear a kill-switch halt after checking the account (MODE=paper|live)
	$(RUN) resume --mode $(MODE)

.PHONY: dashboard
dashboard: $(STAMP) ## Web dashboard (HOST=127.0.0.1 PORT=8080; non-local needs DASHBOARD_TOKEN)
	$(RUN) dashboard --host $(HOST) --port $(PORT)

##@ Background (tmux, survives SSH disconnect)
.PHONY: start
start: $(STAMP) ## Start bot in tmux (MODE=paper|live; real money not allowed here)
	@command -v tmux >/dev/null || { echo "tmux not installed"; exit 1; }
	@if [ "$(MODE)" != paper ] && [ "$(MODE)" != live ]; then echo "MODE must be paper or live"; exit 2; fi
	@if tmux has-session -t $(SESSION) 2>/dev/null; then echo "$(SESSION) already running (make attach / make stop)"; exit 1; fi
	@mkdir -p logs
	tmux new-session -d -s $(SESSION) "bash -lc '$(RUN) $(MODE) 2>&1 | tee -ia logs/$(MODE).log'"
	@sleep 2; tmux has-session -t $(SESSION) 2>/dev/null && echo "started $(SESSION) -> make logs / make attach" \
	    || { echo "bot exited immediately:"; tail -20 logs/$(MODE).log; exit 1; }

.PHONY: stop
stop: ## Gracefully stop the tmux bot (Ctrl+C -> state saved)
	@if tmux has-session -t $(SESSION) 2>/dev/null; then \
	    tmux send-keys -t $(SESSION) C-c; \
	    for i in $$(seq 1 30); do tmux has-session -t $(SESSION) 2>/dev/null || break; sleep 1; done; \
	    if tmux has-session -t $(SESSION) 2>/dev/null; then echo "still running after 30s - check: make attach"; exit 1; fi; \
	    echo "stopped $(SESSION)"; else echo "$(SESSION) not running"; fi

.PHONY: restart
restart: ## Stop then start the tmux bot
	$(MAKE) stop
	$(MAKE) start

.PHONY: attach
attach: ## Attach to the tmux bot (detach: Ctrl+B then D)
	tmux attach -t $(SESSION)

.PHONY: logs
logs: ## Tail the tmux bot log
	@tail -n 100 -f logs/$(MODE).log

.PHONY: ps
ps: ## List running bot tmux sessions
	@tmux ls 2>/dev/null | grep '^binance-bot' || echo "no bot sessions"

##@ Data
.PHONY: backup
backup: $(STAMP) ## Consistent SQLite backup of all bot DBs to backups/ (safe while running)
	$(RUN) backup --dir $(BACKUP_DIR)

.PHONY: clean-reports
clean-reports: ## Delete generated backtest reports
	rm -rf $(OUT)

##@ Docker
.PHONY: docker-build
docker-build: ## Build the image (IMAGE=binance-bot:local)
	docker build -t $(IMAGE) .

.PHONY: up
up: config ## docker compose up (bot + dashboard)
	@mkdir -p data
	$(COMPOSE) up -d --build
	@$(COMPOSE) ps

.PHONY: down
down: ## docker compose down (data/ is kept)
	$(COMPOSE) down

.PHONY: dlogs
dlogs: ## Follow docker compose logs
	$(COMPOSE) logs -f --tail 100

.PHONY: dps
dps: ## docker compose status incl. healthchecks
	$(COMPOSE) ps

.PHONY: dconfig
dconfig: ## Validate docker-compose.yml
	$(COMPOSE) config -q && echo "compose: valid"

##@ Housekeeping
.PHONY: clean
clean: ## Remove caches (keeps venv, data, reports, logs)
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -print0 | xargs -0 rm -rf
	rm -rf .pytest_cache .ruff_cache

.PHONY: distclean
distclean: clean ## clean + remove the venv (data/, backups/, .env, config are never touched)
	rm -rf $(VENV)
