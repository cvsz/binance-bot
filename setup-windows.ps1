# Binance Spot Trading Bot — Windows setup (PowerShell)
# Run in PowerShell: .\setup-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host "== [1/4] Python check ==" -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found. Install from https://www.python.org and add to PATH."
    exit 1
}
python --version

Write-Host "== [2/4] Create virtualenv ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "== [3/4] Install dependencies ==" -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -c constraints.txt

Write-Host "== [4/4] Create config ==" -ForegroundColor Cyan
if (-not (Test-Path "config.yaml")) { Copy-Item config.example.yaml config.yaml }
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }

Write-Host "`n== Setup complete ==" -ForegroundColor Green
Write-Host "Next:"
Write-Host "  1) Edit .env and add your API keys/secrets"
Write-Host "  2) Edit config.yaml if needed"
Write-Host "  3) Run: .\run.bat paper"
