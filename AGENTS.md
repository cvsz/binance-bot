# AGENTS.md — rules for AI agents and contributors

This repository is a **real-money trading bot**. Correctness and safety beat speed.

## Read first
1. `docs/README.md` (index), `docs/ARCHITECTURE.md`, `docs/RISK.md`, `docs/SECURITY.md`
2. Organisation policy: https://github.com/cvsz/zeaz/blob/main/zeaz.md (repository rules below may be stricter, never weaker)

## Environment
- Lives in WSL: `~/binance-bot` (SSH: `ssh -p 2223 cvsz@192.168.1.85`). Use `make` targets; the venv is `.venv/`.
- Gate before every commit: `make ci` (lint, tests, docs, secrets check). Use `make test-fast` while iterating.

## Hard rules
- **Never** read, print, log, copy or commit `.env`, API keys, tokens, `data/*.db`, `backups/`. Check presence with `make doctor`, not `cat`.
- **Never** start real-money trading (`make live-real`, `run.py live --real-money`, `exchange.testnet: false`) or change the real-money gates in `bot/config.py` / `Runner.run()` without explicit human approval in the current conversation.
- **Never** weaken: the mandatory stop-loss, `RiskConfig` validation, the no-lookahead guarantee (`test_no_lookahead`), atomic state saves, read-only dashboard, client-order-id recovery.
- Do not delete `data/` or `backups/`. Destructive git operations (`reset --hard`, force push) need human approval.
- Strategy changes must be justified with backtests over multiple periods; do not tune parameters on the same data you report results on.

## Conventions
- Code, comments, identifiers: English. User-facing docs (`README.md`, `docs/`): Thai.
- Python 3.12+, type hints, `logging` (no `print` in `bot/`), ruff-clean (`make lint`).
- Every bug fix gets a regression test (`tests/test_hardening.py` style). Mark slow tests `@pytest.mark.slow`.
- Tests must not touch the network: use `tests/test_runner.py::FakeExchange` (matches ccxt signatures; supports failure injection).
- Changing behaviour, CLI commands, config keys or make targets → update `docs/`, `README.md` and `CHANGELOG.md` in the same commit.
- Branch per change (`feat/…`, `fix/…`, `docs/…`); commit messages `type: summary`.

## Report format
State what was verified and how (PASS / FAIL / BLOCKED / NOT RUN). Never claim tests passed without running them.
