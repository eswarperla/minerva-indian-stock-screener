@echo off
REM SEPA-VCP India screener launcher (Windows).
REM Run AFTER the NSE close (15:30 IST).
cd /d "%~dp0"

if not exist venv (
  echo [setup] creating virtualenv...
  python -m venv venv
  call venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install yfinance curl_cffi pandas numpy scipy
) else (
  call venv\Scripts\activate.bat
)

echo [run] SEPA-VCP India screener %date% %time%
python sepa_screener_india.py
echo [done] output -^> sepa_data_india_latest.json
pause
