#!/usr/bin/env python3
"""Build Windows 11 release packages for the Binance Spot Trading Bot.

Produces:
  1. reports/release/binance-bot-windows-YYYYMMDD.zip  — full source zip
  2. reports/release/binance-bot-windows-installer.zip — installer-ready package
                                                           (includes installer scripts)

Packages the project so a Windows user can run it with a local Python:
    unzip binance-bot-windows.zip
    cd binance-bot-windows
    python -m venv .venv
    .venv\\Scripts\\activate
    pip install -r requirements.txt -c constraints.txt
    cp .env.example .env   # then fill in your keys
    run.bat paper

For a compiled .exe installer, compile installer/setup-windows.iss with
Inno Setup Compiler on Windows.

Excludes secrets, databases, logs, caches, and git internals.
"""
from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

EXCLUDE_NAMES = {
    ".git", ".gitignore", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    "data", "backups", "logs", "reports", ".env", "config.yaml",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}

INSTALLER_FILES = [
    "bot", "run.py", "config.example.yaml", "requirements.txt",
    "constraints.txt", "requirements-dev.txt", "run.bat",
    "setup-windows.ps1", "README-WINDOWS.md", "README.md",
    "AGENTS.md", "CHANGELOG.md", "pyproject.toml", "Makefile",
    "docker-compose.yml", "Dockerfile", ".dockerignore",
]


def is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    if parts & EXCLUDE_NAMES:
        return True
    if path.name == ".gitignore":
        return True
    return path.name in {".dockerignore", ".gitleaks.toml"}


def zip_files(files: list[Path], root: Path, out_zip: Path) -> None:
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(files):
            arc = p.relative_to(root).as_posix()
            zf.write(p, arc)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "reports" / "release"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    # Full source zip (all non-secret files)
    full_files = [
        p for p in root.rglob("*")
        if p.is_file() and not is_excluded(p, root)
    ]
    zip_files(full_files, root, out_dir / f"binance-bot-windows-{today}.zip")

    # Installer package (curated subset + installer scripts)
    installer_files = [
        root / f for f in INSTALLER_FILES if (root / f).exists()
    ] + [root / "installer" / "install-windows.ps1",
         root / "installer" / "setup-windows.iss"]
    zip_files(installer_files, root,
              out_dir / f"binance-bot-windows-installer-{today}.zip")

    print(f"release: {out_dir / f'binance-bot-windows-{today}.zip'}")
    print(f"release: {out_dir / f'binance-bot-windows-installer-{today}.zip'}")
    print("next: copy to Windows, unzip, run setup-windows.ps1 or run.bat")
    print("      For compiled .exe: compile installer/setup-windows.iss with Inno Setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
