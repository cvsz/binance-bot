"""Centralized engineering bounds for the binance-bot domain.

Adapted from TradingAgents' `contracts/limits.ts`. All bounds are defined once
here and used where they apply; none are user-facing (those live in config.yaml
and RiskConfig).
"""

from __future__ import annotations

# ---- Exchange requests: how long one may take --------------------------------
REQUEST_MS: dict[str, int] = {
    "binance": 30_000,
    "binanceus": 30_000,
    "binanceth": 30_000,
    "model_probe": 5_000,
}

# Bytes of one answer read from an exchange; a longer answer means unavailable.
ANSWER_BYTES = 16_777_216

# ---- Model/exchange steps and their output -----------------------------------
STEP_OUTPUT_TOKENS = 32_768
DEFAULT_OUTPUT_TOKENS = 8_192
FINAL_OUTPUT_TOKENS = 16_384
FINAL_GRACE_MS = 120_000
FALLBACK_CONTEXT_WINDOW = 32_768
STALL_MS = 600_000

# Waits before retrying a step that failed before anything arrived.
RETRY_MS = [1_000, 2_000]

# ---- Tool calls --------------------------------------------------------------
AT_ONCE = 4
PER_STEP = 16
TURN_DATA_CALLS = 6
RESULT_CHARS = 12_000
INTRADAY_BARS = 100
DAILY_WINDOW_DAYS = 366
TEXT_CHARS = 10_000
BRIEF_CHARS = 4_000
AGENT_TITLE_CHARS = 60
BRIEF_RECORDS = 8
SUBAGENTS_STOP_MS = 10_000
MARKETS_PER_EVENT = 3
MARKET_SEARCH_PAGE = 20
LONG_FIELD_CHARS = 1_500
SECTION_HEADROOM_CHARS = 1_500
SYMBOL_CANDIDATES = 10
SERIES_CANDIDATES = 5
INSTRUMENT_MATCHES = 10
REFERENCE_RATES = 100

# ---- Fitting conversations (candle windows) into context ---------------------
CHARS_PER_TOKEN = 2
SAVED_CHARS_PER_TOKEN = 4
MARGIN_TOKENS = 2048
MIN_ELIDED_CHARS = 400
SUMMARY_TOKENS = 8_192
SUMMARY_MS = 120_000
ARGUMENT_CHARS = 300
TRANSCRIPT_SLACK_CHARS = 64
SHORTEN_SLACK_CHARS = 100
RETRY_WINDOW_SHARE = 0.8

# ---- Memory: notes, decisions, lessons ---------------------------------------
NOTE_CHARS = 300
INSTRUMENT_CHARS = 20
HORIZON_CHARS = 60
THESIS_CHARS = 1_200
NOTES_IN_CONTEXT = 40
NOTES_CONTEXT_CHARS = 4_000
RECALL_SAME = 5
RECALL_OTHER = 3
RECALL_CHARS = 6_000
SETTLEMENTS_PER_RECALL = 3
LESSON_TOKENS = 1_024
LESSON_MS = 60_000
GIVE_UP_DAYS = 45
GAP_PATIENCE_DAYS = 30
APPEND_WAIT_MS = 10_000
APPEND_POLL_MS = 50

# ---- Copying sessions/databases to backups -----------------------------------
CHUNK_BYTES = 1_000_000
BACKUP_RETRY_MS = [2_000, 10_000, 60_000]
DRAIN_MS = 10_000
STOP_WAIT_MS = 5_000
LISTED_PAGES = 5

# ---- Recorded tool results (evidence) ----------------------------------------
RECORD_BYTES = 1_048_576
SESSION_BYTES = 16 * 1_048_576
LINE_BYTES = CHUNK_BYTES - 4_096
PREVIEW_CHARS = 600

# ---- Keys --------------------------------------------------------------------
KEY_MIN_CHARS = 8
KEY_SCRUB_MIN_CHARS = 4

# ---- Agent files -------------------------------------------------------------
AGENT_FILE_STEPS_DEFAULT = 15
AGENT_FILE_STEPS_MAX = 30

# ---- Update check ------------------------------------------------------------
UPDATES_CHECK_EVERY_MS = 86_400_000
UPDATES_ANSWER_BYTES = 1_048_576
UPDATES_EXECUTABLE_BYTES = 536_870_912
UPDATES_SUMS_BYTES = 65_536

# ---- Interactive app ---------------------------------------------------------
APP_LEAVE_GRACE_MS = 2_000
APP_PASTE_QUIET_MS = 250
APP_SPINNER_MS = 80
APP_CLIPBOARD_TERMINAL_BYTES = 100_000
APP_CLIPBOARD_TOOL_MS = 2_000

# ---- Trading loop backoff ----------------------------------------------------
MAX_BACKOFF_SECONDS = 600

# ---- Sessions ----------------------------------------------------------------
SESSIONS_LISTED = 50
SESSIONS_REPLAY_TURNS = 20
SESSIONS_HEAD_BYTES = 8_192

# ---- Portfolio tools ---------------------------------------------------------
PORTFOLIO_HOLDINGS = 20
PORTFOLIO_WEIGHT_SUM_TOLERANCE = 1e-9
PORTFOLIO_VARIANCE_TOLERANCE = 1e-12
PORTFOLIO_FRONTIER_POINTS = 10

# ---- Optimizer ---------------------------------------------------------------
OPTIMIZER_ACTIVE_SET_ITERATIONS = 1_000
OPTIMIZER_RISK_PARITY_SWEEPS = 10_000
OPTIMIZER_TOLERANCE = 1e-13
OPTIMIZER_SEARCH_STEPS = 60
OPTIMIZER_END_TOLERANCE = 1e-10
OPTIMIZER_SHARE_TOLERANCE = 1e-8

# ---- Indicators tool ---------------------------------------------------------
INDICATORS_PER_CALL = 6
INDICATORS_MAX_PERIOD = 250
INDICATORS_EVENTS = 10
INDICATORS_TAIL = 10

__all__ = [
    "REQUEST_MS",
    "ANSWER_BYTES",
    "STEP_OUTPUT_TOKENS",
    "DEFAULT_OUTPUT_TOKENS",
    "FINAL_OUTPUT_TOKENS",
    "FINAL_GRACE_MS",
    "FALLBACK_CONTEXT_WINDOW",
    "STALL_MS",
    "RETRY_MS",
    "AT_ONCE",
    "PER_STEP",
    "TURN_DATA_CALLS",
    "RESULT_CHARS",
    "INTRADAY_BARS",
    "DAILY_WINDOW_DAYS",
    "TEXT_CHARS",
    "BRIEF_CHARS",
    "AGENT_TITLE_CHARS",
    "BRIEF_RECORDS",
    "SUBAGENTS_STOP_MS",
    "MARKETS_PER_EVENT",
    "MARKET_SEARCH_PAGE",
    "LONG_FIELD_CHARS",
    "SECTION_HEADROOM_CHARS",
    "SYMBOL_CANDIDATES",
    "SERIES_CANDIDATES",
    "INSTRUMENT_MATCHES",
    "REFERENCE_RATES",
    "CHARS_PER_TOKEN",
    "SAVED_CHARS_PER_TOKEN",
    "MARGIN_TOKENS",
    "MIN_ELIDED_CHARS",
    "SUMMARY_TOKENS",
    "SUMMARY_MS",
    "ARGUMENT_CHARS",
    "TRANSCRIPT_SLACK_CHARS",
    "SHORTEN_SLACK_CHARS",
    "RETRY_WINDOW_SHARE",
    "NOTE_CHARS",
    "INSTRUMENT_CHARS",
    "HORIZON_CHARS",
    "THESIS_CHARS",
    "NOTES_IN_CONTEXT",
    "NOTES_CONTEXT_CHARS",
    "RECALL_SAME",
    "RECALL_OTHER",
    "RECALL_CHARS",
    "SETTLEMENTS_PER_RECALL",
    "LESSON_TOKENS",
    "LESSON_MS",
    "GIVE_UP_DAYS",
    "GAP_PATIENCE_DAYS",
    "APPEND_WAIT_MS",
    "APPEND_POLL_MS",
    "CHUNK_BYTES",
    "BACKUP_RETRY_MS",
    "DRAIN_MS",
    "STOP_WAIT_MS",
    "LISTED_PAGES",
    "RECORD_BYTES",
    "SESSION_BYTES",
    "LINE_BYTES",
    "PREVIEW_CHARS",
    "KEY_MIN_CHARS",
    "KEY_SCRUB_MIN_CHARS",
    "AGENT_FILE_STEPS_DEFAULT",
    "AGENT_FILE_STEPS_MAX",
    "UPDATES_CHECK_EVERY_MS",
    "UPDATES_ANSWER_BYTES",
    "UPDATES_EXECUTABLE_BYTES",
    "UPDATES_SUMS_BYTES",
    "APP_LEAVE_GRACE_MS",
    "APP_PASTE_QUIET_MS",
    "APP_SPINNER_MS",
    "APP_CLIPBOARD_TERMINAL_BYTES",
    "APP_CLIPBOARD_TOOL_MS",
    "MAX_BACKOFF_SECONDS",
    "SESSIONS_LISTED",
    "SESSIONS_REPLAY_TURNS",
    "SESSIONS_HEAD_BYTES",
    "PORTFOLIO_HOLDINGS",
    "PORTFOLIO_WEIGHT_SUM_TOLERANCE",
    "PORTFOLIO_VARIANCE_TOLERANCE",
    "PORTFOLIO_FRONTIER_POINTS",
    "OPTIMIZER_ACTIVE_SET_ITERATIONS",
    "OPTIMIZER_RISK_PARITY_SWEEPS",
    "OPTIMIZER_TOLERANCE",
    "OPTIMIZER_SEARCH_STEPS",
    "OPTIMIZER_END_TOLERANCE",
    "OPTIMIZER_SHARE_TOLERANCE",
    "INDICATORS_PER_CALL",
    "INDICATORS_MAX_PERIOD",
    "INDICATORS_EVENTS",
    "INDICATORS_TAIL",
]
