@echo off
:: Binance Spot Trading Bot — Windows runner
:: Usage: run.bat [paper|live|backtest|dashboard|status|health|resume|backup] [args...]

setlocal

if not exist .venv\Scripts\python.exe (
    echo venv not found. Run setup first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt -c constraints.txt
    goto :end
)

call .venv\Scripts\activate.bat

if "%1"=="" (
    python run.py
) else (
    python run.py %*
)

:end
pause
