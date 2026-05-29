#!/usr/bin/env bash
# SEPA-VCP India screener launcher (Mac/Linux).
# Run AFTER the NSE close (15:30 IST). First run takes ~10-20 min for the seed
# list (longer for the full Nifty 500); same-day re-runs are instant via cache.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# Create venv on first run
if [ ! -d "venv" ]; then
  echo "[setup] creating virtualenv..."
  "$PY" -m venv venv
  ./venv/bin/pip install --upgrade pip >/dev/null
  ./venv/bin/pip install yfinance curl_cffi pandas numpy scipy
fi

echo "[run] SEPA-VCP India screener $(date)"
./venv/bin/python sepa_screener_india.py 2>&1 | tee -a screener_india.log

echo "[render] building dashboard HTML..."
./venv/bin/python build_dashboard_india.py 2>&1 | tee -a screener_india.log
echo "[done] output -> sepa_data_india_latest.json + sepa_vcp_india_watchlist.html"
