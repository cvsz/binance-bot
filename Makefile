# Binance Spot Trading Bot — developer & operator commands
#   make            -> list targets
#   make setup      -> venv + deps + config files (first time)
#   make ci         -> full quality gate (run before every commit / merge)
# Override variables on the command line, e.g.  make backtest DAYS=180  |  make status MODE=live
# Docs: docs/CLI.md

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
MAKEFLAGS += --no-print-directory

# ---- variables ---------------------------------------------------------------
PYTHON     ?= python3
VENV       ?= .venv
PY         := $(VENV)/bin/python
PIP        := $(PY) -m pip
CONFIG     ?= config.yaml
MODE       ?= paper
DAYS       ?= 90
SYMBOL     ?= BTCUSDT
INTERVAL   ?= 15m
START      ?=
END        ?=
DATA_FILE  ?=
CSV        ?=
OUT        ?= reports
HOST       ?= 127.0.0.1
PORT       ?= 8080
ARGS       ?=
FILE       ?=
CONFIRM    ?=
VERBOSE    ?=
SESSION    ?= binance-bot-$(MODE)
BACKUP_DIR ?= backups
LOG_DIR    ?= logs
COMPOSE    ?= docker compose
IMAGE      ?= binance-bot:local
STAMP      := $(VENV)/.installed
RUN        := $(PY) run.py -c $(CONFIG)
TS         := $(shell date +%Y%m%d-%H%M%S)
VERBOSE_FLAG := $(if $(filter 1 yes true,$(VERBOSE)),-v,)
HAVE_DOCKER  := $(shell command -v docker >/dev/null 2>&1 && echo yes)
HAVE_TMUX    := $(shell command -v tmux >/dev/null 2>&1 && echo yes)

# ---- reusable guards ---------------------------------------------------------
# $(call check_mode) - MODE must be paper|live
define check_mode
@case "$(MODE)" in paper|live) ;; *) echo "MODE must be paper or live (got '$(MODE)')"; exit 2;; esac
endef
# $(call check_stopped) - refuse while ANY bot process for MODE runs (tmux under any session name,
# foreground, or docker) - matched on the process command line, not on the tmux session name
define check_stopped
@if pids=$$(pgrep -f "run[.]py( -c [^ ]+)?( -v)? $(MODE)( |$$)"); then \
	echo "a $(MODE) bot is running (pid $$(echo $$pids | tr '\n' ' ')) - stop it first (make stop / make down)"; exit 1; fi
@if [ -n "$(HAVE_DOCKER)" ] && [ -n "$$($(COMPOSE) ps -q bot 2>/dev/null)" ]; then \
	echo "bot container is up - run: make down"; exit 1; fi
endef
# $(call db_file) - shell expression resolving the DB path for MODE (testnet-aware)
db_file = $$($(PY) -c 'import sys; from bot.config import load_config, db_path_for; print(db_path_for(load_config(sys.argv[1]), sys.argv[2]))' '$(CONFIG)' '$(MODE)')

# ---- help --------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@awk 'BEGIN{FS=":.*## "} /^##@/{printf "\n\033[1m%s\033[0m\n", substr($$0,5)} \
	    /^[a-zA-Z0-9_.-]+:.*## /{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nVariables: MODE=%s CONFIG=%s DAYS=%s HOST=%s PORT=%s  (full list: docs/CLI.md)\n" \
	    "$(MODE)" "$(CONFIG)" "$(DAYS)" "$(HOST)" "$(PORT)"

##@ Setup
$(STAMP): requirements.txt requirements-dev.txt constraints.txt
	@test -x $(PY) || { echo "creating $(VENV) with $$($(PYTHON) --version)"; $(PYTHON) -m venv $(VENV); }
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements-dev.txt -c constraints.txt
	@touch $@

.PHONY: install
install: $(STAMP) ## Create .venv and install pinned deps (no-op when up to date)
	@echo "venv ready: $(VENV) ($$($(PY) --version), ccxt $$($(PY) -c 'import ccxt; print(ccxt.__version__)'))"

.PHONY: reinstall
reinstall: ## Force reinstall of all dependencies into the existing venv
	@rm -f $(STAMP)
	@$(MAKE) install

.PHONY: config
config: ## Create config.yaml / .env from the examples if missing (never overwrites)
	@if [ ! -f $(CONFIG) ]; then cp config.example.yaml $(CONFIG); echo "created $(CONFIG)"; else echo "$(CONFIG) exists, kept"; fi
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env"; else echo ".env exists, kept"; fi
	@chmod 600 .env
	@mkdir -p data

.PHONY: setup
setup: install config perms ## First-time setup: install + config + permissions
	@echo "setup done -> next: make doctor && make backtest"

.PHONY: perms
perms: ## Lock down file permissions (.env 600, project dir 755, config 644)
	@chmod 755 .
	@[ ! -f .env ] || chmod 600 .env
	@[ ! -f $(CONFIG) ] || chmod 644 $(CONFIG)
	@stat -c '  %a %n' . $$(ls -d .env $(CONFIG) 2>/dev/null)

.PHONY: lock
lock: $(STAMP) ## Re-pin constraints.txt from the venv (runs `make check` first)
	@$(MAKE) check
	@{ echo "# Exact versions the test-suite passed with (pip install -r requirements.txt -c constraints.txt)."; \
	   echo "# Regenerate: make lock"; $(PIP) freeze --exclude-editable; } > constraints.txt.tmp
	@mv constraints.txt.tmp constraints.txt
	@touch $(STAMP)
	@echo "constraints.txt updated - review: git diff constraints.txt"

.PHONY: doctor
doctor: ## Diagnose environment: python, venv, config, secrets (names only), tools
	@echo "python : $$($(PYTHON) --version 2>&1)"
	@if [ -x $(PY) ]; then echo "venv   : $$($(PY) --version) ($(VENV))$$([ -f $(STAMP) ] || echo '  <- deps not installed: make install')"; \
	 else echo "venv   : MISSING -> make install"; fi
	@if [ ! -f $(CONFIG) ]; then echo "config : MISSING -> make config"; \
	 elif [ -x $(PY) ]; then $(PY) -c "from bot.config import load_config; c=load_config('$(CONFIG)'); \
print(f'config : OK {c.symbol} {c.timeframe} strategy={c.strategy} testnet={c.testnet}')" 2>&1 || echo "config : INVALID (see above)"; fi
	@if [ -f .env ]; then \
	    echo ".env   : perms $$(stat -c %a .env)$$([ "$$(stat -c %a .env)" = 600 ] || echo '  <- run: make perms')"; \
	    for k in BINANCE_TESTNET_API_KEY BINANCE_TESTNET_API_SECRET BINANCE_API_KEY BINANCE_API_SECRET BINANCEUS_TESTNET_API_KEY BINANCEUS_TESTNET_API_SECRET BINANCEUS_API_KEY BINANCEUS_API_SECRET TELEGRAM_BOT_TOKEN DASHBOARD_TOKEN BOT_CONFIRM_REAL_MONEY; do \
	        v=$$( { grep -E "^$$k=" .env || true; } | head -1 | cut -d= -f2-); \
	        printf '         %-26s %s\n' "$$k" "$$( [ -n "$$v" ] && echo set || echo empty)"; done; \
	else echo ".env   : MISSING -> make config"; fi
	@echo "docker : $$( [ -n "$(HAVE_DOCKER)" ] && docker --version || echo 'not installed')"
	@echo "tmux   : $$( [ -n "$(HAVE_TMUX)" ] && tmux -V || echo 'not installed (needed for start/stop)')"
	@echo "git    : $$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-') @ $$(git log -1 --format=%h 2>/dev/null || echo '-')$$( [ -z "$$(git status --porcelain 2>/dev/null)" ] || echo ' (uncommitted changes)')"

.PHONY: info
info: $(STAMP) ## Versions, git state, bot sessions and databases
	@echo "git     : $$(git rev-parse --abbrev-ref HEAD) @ $$(git log -1 --format='%h %s')"
	@echo "python  : $$($(PY) --version)  ccxt $$($(PY) -c 'import ccxt; print(ccxt.__version__)')  pandas $$($(PY) -c 'import pandas; print(pandas.__version__)')"
	@echo "sessions: $$( [ -n "$(HAVE_TMUX)" ] && (tmux ls 2>/dev/null | grep -o '^binance-bot[^:]*' | tr '\n' ' ') || true)"
	@echo "dbs     :"; ls -l data/*.db 2>/dev/null | awk '{printf "          %s  %s %s %s\n", $$9, $$6, $$7, $$8}' || echo "          none"

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
fmt-check: $(STAMP) ## Show formatting differences (informational, does not modify files)
	$(PY) -m ruff format --check --diff . || true

.PHONY: docs-check
docs-check: $(STAMP) ## Verify every relative link/anchor in the Markdown docs
	$(PY) scripts/check_docs.py .

.PHONY: secrets-check
secrets-check: $(STAMP) ## Fail if secrets/DBs are tracked, look committed, or .env is not 600
	$(PY) scripts/check_secrets.py .

.PHONY: check
check: lint test ## Lint + tests
	@echo "check: PASS"

.PHONY: ci
ci: lint docs-check secrets-check test ## Full gate: lint, docs, secrets, tests (+ compose config if docker)
	@if [ -n "$(HAVE_DOCKER)" ]; then $(COMPOSE) config -q && echo "compose: valid"; else echo "compose: skipped (no docker)"; fi
	@echo "ci: PASS"

##@ Trading
.PHONY: require-config
require-config:
	@[ -f $(CONFIG) ] || { echo "$(CONFIG) not found - run: make config"; exit 2; }

.PHONY: backtest
backtest: $(STAMP) require-config ## Backtest (DAYS=90 | CSV=file.csv, OUT=reports, VERBOSE=1)
	@if [ -n "$(CSV)" ] && [ ! -f "$(CSV)" ]; then echo "CSV not found: $(CSV)"; exit 2; fi
	$(RUN) $(VERBOSE_FLAG) backtest $(if $(CSV),--csv $(CSV),--days $(DAYS)) --out $(OUT)

.PHONY: paper
paper: $(STAMP) require-config ## Paper trading in the foreground (live prices, simulated money)
	$(RUN) $(VERBOSE_FLAG) paper

.PHONY: live
live: $(STAMP) require-config ## Live trading; Binance TESTNET when exchange.testnet: true
	$(RUN) $(VERBOSE_FLAG) live

.PHONY: live-real
live-real: $(STAMP) require-config ## REAL MONEY (foreground). Needs CONFIRM=YES_I_ACCEPT_THE_RISK + .env gate
	@if [ "$(CONFIRM)" != "YES_I_ACCEPT_THE_RISK" ]; then \
	    echo "refusing: run  make live-real CONFIRM=YES_I_ACCEPT_THE_RISK  (and set BOT_CONFIRM_REAL_MONEY in .env)"; exit 2; fi
	$(RUN) $(VERBOSE_FLAG) live --real-money

.PHONY: status
status: $(STAMP) require-config ## Position, risk state, recent trades (MODE=paper|live)
	$(call check_mode)
	$(RUN) status --mode $(MODE)

.PHONY: health
health: $(STAMP) require-config ## Exit 0 if the bot heartbeat is fresh (MODE=paper|live)
	$(call check_mode)
	$(RUN) health --mode $(MODE)

.PHONY: resume
resume: $(STAMP) require-config ## Clear a kill-switch halt after checking the account (MODE=paper|live)
	$(call check_mode)
	$(RUN) resume --mode $(MODE)

.PHONY: dashboard
dashboard: $(STAMP) require-config ## Web dashboard (HOST=127.0.0.1 PORT=8080; non-local needs DASHBOARD_TOKEN)
	$(RUN) dashboard --host $(HOST) --port $(PORT)

##@ Background (tmux, survives SSH disconnect)
.PHONY: start
start: $(STAMP) require-config ## Start bot in tmux (MODE=paper|live; real money not allowed here)
	@[ -n "$(HAVE_TMUX)" ] || { echo "tmux not installed"; exit 1; }
	$(call check_mode)
	@if tmux has-session -t $(SESSION) 2>/dev/null; then echo "$(SESSION) already running (make attach / make stop)"; exit 1; fi
	@mkdir -p $(LOG_DIR)
	@echo "=== $(TS) start $(MODE) ($$(git log -1 --format=%h 2>/dev/null || echo nogit)) ===" >> $(LOG_DIR)/$(MODE).log
	tmux new-session -d -s $(SESSION) "bash -lc '$(RUN) $(MODE) 2>&1 | tee -ia $(LOG_DIR)/$(MODE).log'"
	@sleep 3; if tmux has-session -t $(SESSION) 2>/dev/null; then echo "started $(SESSION) -> make logs MODE=$(MODE) / make health MODE=$(MODE)"; \
	    else echo "bot exited immediately:"; tail -20 $(LOG_DIR)/$(MODE).log; exit 1; fi

.PHONY: stop
stop: ## Gracefully stop the tmux bot (Ctrl+C -> state saved, waits up to 30s)
	@if [ -n "$(HAVE_TMUX)" ] && tmux has-session -t $(SESSION) 2>/dev/null; then \
	    tmux send-keys -t $(SESSION) C-c; \
	    for i in $$(seq 1 30); do tmux has-session -t $(SESSION) 2>/dev/null || break; sleep 1; done; \
	    if tmux has-session -t $(SESSION) 2>/dev/null; then echo "still running after 30s - check: make attach MODE=$(MODE)"; exit 1; fi; \
	    echo "stopped $(SESSION)"; else echo "$(SESSION) not running"; fi

.PHONY: restart
restart: ## Stop then start the tmux bot
	@$(MAKE) stop
	@$(MAKE) start

.PHONY: attach
attach: ## Attach to the tmux bot (detach: Ctrl+B then D)
	tmux attach -t $(SESSION)

.PHONY: logs
logs: ## Follow the tmux bot log (MODE=paper|live)
	@[ -f $(LOG_DIR)/$(MODE).log ] || { echo "no log yet: $(LOG_DIR)/$(MODE).log"; exit 1; }
	tail -n 100 -f $(LOG_DIR)/$(MODE).log

.PHONY: errors
errors: ## Show recent warnings/errors from all bot logs
	@grep -hE "WARNING|ERROR|CRITICAL|HALTED|STOPPED" $(LOG_DIR)/*.log 2>/dev/null | tail -n 50 || echo "no warnings/errors logged"

.PHONY: ps
ps: ## List running bot tmux sessions
	@tmux ls 2>/dev/null | grep '^binance-bot' || echo "no bot sessions"

##@ Data
.PHONY: public-data
public-data: $(STAMP) ## Download Binance public klines -> CSV for backtest (SYMBOL/INTERVAL/DAYS or START/END)
	@mkdir -p data $(OUT)
	$(PY) scripts/fetch_public_data.py --symbol $(SYMBOL) --interval $(INTERVAL) \
	    $(if $(START),--start $(START),--days $(DAYS)) $(if $(END),--end $(END),) \
	    --out $(if $(DATA_FILE),$(DATA_FILE),$(OUT)/public_$(SYMBOL)_$(INTERVAL).csv)

.PHONY: backup
backup: $(STAMP) require-config ## Consistent SQLite backup of all bot DBs to backups/ (safe while running)
	$(RUN) backup --dir $(BACKUP_DIR)

.PHONY: backups
backups: ## List available backups
	@ls -lh $(BACKUP_DIR)/ 2>/dev/null || echo "no backups yet - make backup"

.PHONY: restore
restore: $(STAMP) require-config ## Restore FILE=backups/x.db into MODE's DB (bot must be stopped; current DB is kept)
	$(call check_mode)
	@[ -n "$(FILE)" ] && [ -f "$(FILE)" ] || { echo "usage: make restore MODE=paper FILE=backups/bot.paper.<ts>.db"; exit 2; }
	@FILE="$(FILE)" $(PY) -c 'import os, sqlite3, sys; \
c = sqlite3.connect("file:" + os.environ["FILE"] + "?mode=ro", uri=True); \
ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; \
t = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}; \
sys.exit(0 if ok and {"trades", "state", "equity"} <= t else 1)' 2>/dev/null \
	    || { echo "$(FILE) is not a valid bot database - nothing changed"; exit 2; }
	$(call check_stopped)
	@db=$(db_file); mkdir -p $(BACKUP_DIR)/pre-restore-$(TS); \
	    for f in "$$db" "$$db-wal" "$$db-shm"; do [ ! -f "$$f" ] || mv "$$f" $(BACKUP_DIR)/pre-restore-$(TS)/; done; \
	    mkdir -p "$$(dirname "$$db")"; cp "$(FILE)" "$$db"; \
	    echo "restored $(FILE) -> $$db (previous DB saved in $(BACKUP_DIR)/pre-restore-$(TS)/)"

.PHONY: reset-paper
# always paper, even if MODE=live is passed on the command line
reset-paper: override MODE := paper
reset-paper: override SESSION := binance-bot-paper
reset-paper: $(STAMP) require-config ## Start paper trading fresh (old paper DB is moved to backups/, not deleted)
	$(call check_stopped)
	@db=$(db_file); if ls "$$db"* >/dev/null 2>&1; then mkdir -p $(BACKUP_DIR)/paper-reset-$(TS); \
	    mv "$$db"* $(BACKUP_DIR)/paper-reset-$(TS)/; echo "moved paper DB to $(BACKUP_DIR)/paper-reset-$(TS)/"; \
	    else echo "no paper DB - already fresh"; fi

.PHONY: clean-reports
clean-reports: ## Delete generated backtest reports
	rm -rf $(OUT)

##@ Docker
.PHONY: docker-build
docker-build: ## Build the image (IMAGE=binance-bot:local)
	docker build -t $(IMAGE) .

.PHONY: up
up: config ## docker compose up: bot (MODE=paper|live) + dashboard (needs DASHBOARD_TOKEN)
	$(call check_mode)
	@grep -qE '^DASHBOARD_TOKEN=.+' .env || { echo "DASHBOARD_TOKEN is empty in .env - set it before make up (dashboard binds 0.0.0.0)"; exit 2; }
	@mkdir -p data
	BOT_MODE=$(MODE) $(COMPOSE) up -d --build
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
clean: ## Remove caches (keeps venv, data, backups, reports, logs)
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -print0 | xargs -0 rm -rf
	rm -rf .pytest_cache .ruff_cache

.PHONY: distclean
distclean: clean ## clean + remove the venv (data/, backups/, logs/, .env, config are never touched)
	rm -rf $(VENV)
