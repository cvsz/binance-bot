#!/usr/bin/env pwsh
# Binance Spot Trading Bot — Windows Installer
# Run in PowerShell: .\install-windows.ps1
# Supports: -InstallDir, -Mode (paper|live), -StartAfterInstall

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$InstallDir = "$env:USERPROFILE\BinanceSpotTradingBot",
    
    [Parameter(Mandatory=$false)]
    [ValidateSet('paper','live')]
    [string]$Mode = 'paper',
    
    [Parameter(Mandatory=$false)]
    [switch]$StartAfterInstall
)

$ErrorActionPreference = 'Stop'
$ScriptVersion = '1.0.0'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host @"
╔═══════════════════════════════════════════════════════════════════════════╗
║  Binance Spot Trading Bot — Windows Installer v$ScriptVersion          ║
║                                                                          ║
║  ⚠️  REAL MONEY TRADING BOT — Use with caution                          ║
║  Only trade money you can afford to lose                               ║
╚═══════════════════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# Step 1: Check Python
# -----------------------------------------------------------------------------
Write-Host "`n[1/6] Checking Python..." -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.12+ from https://www.python.org`n" +
                "Make sure to 'Add Python to PATH' during installation."
    exit 1
}
$pyVersion = python --version 2>&1
Write-Host "  ✓ $pyVersion" -ForegroundColor Green

# -----------------------------------------------------------------------------
# Step 2: Create install directory
# -----------------------------------------------------------------------------
Write-Host "`n[2/6] Creating install directory: $InstallDir" -ForegroundColor Cyan
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
Set-Location $InstallDir

# -----------------------------------------------------------------------------
# Step 3: Copy files
# -----------------------------------------------------------------------------
Write-Host "`n[3/6] Copying bot files..." -ForegroundColor Cyan
$sourceFiles = @(
    'bot', 'run.py', 'config.example.yaml', 'requirements.txt', 'constraints.txt',
    'requirements-dev.txt', 'run.bat', 'AGENTS.md', 'CHANGELOG.md', 'README.md',
    'README-WINDOWS.md', 'pyproject.toml', 'Makefile', 'docker-compose.yml',
    'Dockerfile', '.dockerignore', '.gitignore'
)

foreach ($item in $sourceFiles) {
    $src = Join-Path $ScriptDir $item
    $dst = Join-Path $InstallDir $item
    if (Test-Path $src) {
        if (Test-Path $src -PathType Container) {
            Copy-Item $src -Destination $dst -Recurse -Force
        } else {
            Copy-Item $src -Destination $dst -Force
        }
        Write-Host "  ✓ $item" -ForegroundColor Green
    } else {
        Write-Warning "  ⚠ $item not found, skipping"
    }
}

# -----------------------------------------------------------------------------
# Step 4: Create config files from examples
# -----------------------------------------------------------------------------
Write-Host "`n[4/6] Creating configuration files..." -ForegroundColor Cyan

if (-not (Test-Path "config.yaml")) {
    Copy-Item config.example.yaml config.yaml
    Write-Host "  ✓ config.yaml created" -ForegroundColor Green
} else {
    Write-Host "  ⚠ config.yaml exists, keeping existing" -ForegroundColor Yellow
}

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "  ✓ .env created" -ForegroundColor Green
} else {
    Write-Host "  ⚠ .env exists, keeping existing" -ForegroundColor Yellow
}

# Set .env permissions (Windows equivalent - restrict access)
try {
    $acl = Get-Acl .env
    $acl.SetAccessRuleProtection($true, $false)  # Disable inheritance, remove existing
    $acl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent(),
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow)))
    Set-Acl .env $acl
    Write-Host "  ✓ .env permissions restricted to current user" -ForegroundColor Green
} catch {
    Write-Warning "  ⚠ Could not set .env permissions: $_" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# Step 5: Create virtual environment and install dependencies
# -----------------------------------------------------------------------------
Write-Host "`n[5/6] Creating virtual environment and installing dependencies..." -ForegroundColor Cyan
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
    Write-Host "  ✓ Virtual environment created" -ForegroundColor Green
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -c constraints.txt
Write-Host "  ✓ Dependencies installed" -ForegroundColor Green

# -----------------------------------------------------------------------------
# Step 6: Verify installation
# -----------------------------------------------------------------------------
Write-Host "`n[6/6] Verifying installation..." -ForegroundColor Cyan
python -c "import ccxt; print(f'  ✓ ccxt {ccxt.__version__}')" -ForegroundColor Green
python -c "import pandas; print(f'  ✓ pandas {pandas.__version__}')" -ForegroundColor Green
python -c "from bot.config import load_config; c=load_config('config.yaml'); print(f'  ✓ Config loads OK: {c.symbol} {c.timeframe} {c.strategy}')" -ForegroundColor Green

# -----------------------------------------------------------------------------
# Step 7: Final instructions
# -----------------------------------------------------------------------------
Write-Host @"
╔═══════════════════════════════════════════════════════════════════════════╗
║  INSTALLATION COMPLETE                                                   ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  Install directory: $InstallDir                                          ║
║                                                                          ║
║  NEXT STEPS:                                                             ║
║   1. Edit .env  → Add your Binance API keys/secrets                     ║
║   2. Edit config.yaml → Adjust symbol, timeframe, strategy, risk       ║
║   3. Run: .\run.bat paper     → Paper trading (recommended first)      ║
║   4. Run: .\run.bat live      → Testnet (if testnet: true in config)   ║
║   5. Run: .\run.bat live --real-money  → REAL MONEY (only if ready!)   ║
║                                                                          ║
║  ⚠️  IMPORTANT SAFETY WARNINGS                                           ║
║   • Stop-loss is bot-side — if PC sleeps/network drops, stops won't work ║
║   • Dashboard binds to 127.0.0.1:8080 by default — don't expose publicly ║
║   • Never commit .env or config.yaml to git                             ║
║   • Only trade money you can afford to lose                             ║
║                                                                          ║
╚═══════════════════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Green

if ($StartAfterInstall) {
    Write-Host "`nStarting bot in $Mode mode..." -ForegroundColor Cyan
    .\run.bat $Mode
}