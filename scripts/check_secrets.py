#!/usr/bin/env python3
"""Fail if secrets could leak: sensitive files tracked by git, .env readable by others,
or credential-looking values in tracked files. Never prints secret values."""
from __future__ import annotations

import re
import stat
import subprocess
import sys
from pathlib import Path

FORBIDDEN_TRACKED = re.compile(r"(^|/)(\.env(\..+)?|config\.yaml|[^/]+\.db(-wal|-shm)?)$")
ALLOWED_TRACKED = {".env.example", "config.example.yaml"}
# KEY=value / key: value with a long token-like value (Binance keys are 64 chars)
CRED_RE = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret|token|password)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{24,})")
PLACEHOLDER_RE = re.compile(r"[A-Z0-9_]+")  # env-var names / constants, not values


def tracked_files(root: Path) -> list[str]:
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]  # tracked + new, not ignored
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return [f for f in out.stdout.splitlines() if f]


def main(root: Path) -> int:
    problems: list[str] = []
    files = tracked_files(root)
    for f in files:
        if FORBIDDEN_TRACKED.search(f) and Path(f).name not in ALLOWED_TRACKED:
            problems.append(f"sensitive file tracked by git: {f}")
    for f in files:
        p = root / f
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = CRED_RE.search(line)
            if m and not PLACEHOLDER_RE.fullmatch(m.group(2)):
                problems.append(f"credential-like value in {f}:{n} (key '{m.group(1)}')")
    env = root / ".env"
    if env.exists():
        mode = stat.S_IMODE(env.stat().st_mode)
        if mode & 0o077:
            problems.append(f".env permissions are {oct(mode)[2:]} (expected 600) -> make perms")
    for p in problems:
        print("SECRET-CHECK", p)
    print(f"secrets-check: {len(files)} files (tracked + untracked), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
