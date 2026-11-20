#!/usr/bin/env python3
"""Build a Windows 11 release zip for the Binance Spot Trading Bot.

Packages the project so a Windows user can run it with a local Python:
    unzip binance-bot-windows.zip
    cd binance-bot-windows
    python -m venv .venv
    .venv\\Scripts\\activate
    pip install -r requirements.txt -c constraints.txt
    cp .env.example .env   # then fill in your keys
    run.bat paper

Excludes secrets, databases, logs, caches, and git internals.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

EXCLUDE_NAMES = {
    ".git", ".gitignore", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    "data", "backups", "logs", "reports", ".env", "config.yaml",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}


def is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    if parts & EXCLUDE_NAMES:
        return True
    if path.name == ".gitignore":
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if path.name in {".dockerignore", ".gitleaks.toml"}:
        return True
    return False


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "reports" / "release"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    out_zip = out_dir / f"binance-bot-windows-{today}.zip"

    files = [p for p in root.rglob("*") if p.is_file() and not is_excluded(p, root)]
    files.sort()

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arc = p.relative_to(root).as_posix()
            zf.write(p, arc)

    print(f"release: {out_zip} ({len(files)} files)")
    print("next: copy to Windows, unzip, run setup-windows.ps1 or run.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
