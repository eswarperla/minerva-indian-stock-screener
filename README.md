# SEPA-VCP Daily Stock Screener — India (NSE) edition

A Mark Minervini SEPA + Volatility Contraction Pattern screener for the **Indian market (NSE)**. It is a fork of the US Russell-1000 screener, reusing the same trend-template, VCP, relative-strength, scoring, and bucketing logic. Only the market-specific layers were changed.

This is a **separate, self-contained project** — it does not touch the US screener.

Buckets (identical to the US version):

- **A — At Pivot:** tight VCP, within 3% of breakout pivot, dry volume
- **B — Just Broke Out:** crossed pivot in last 1–3 days with volume confirmation
- **C — Developing Base:** trend + fundamentals pass, base forming but >3% from pivot
- **D — Failed Breakout:** broke out then reversed (avoid)
- **E — Developing, Too Early:** trend + RS pass but base age <3 weeks

---

## What changed vs. the US screener

| Layer | US | India |
|---|---|---|
| Universe | Russell 1000 (Wikipedia) | NIFTY 500 (`build_universe_india.py`) |
| Ticker format | `AAPL` | `RELIANCE.NS` (yfinance NSE suffix) |
| Benchmark | SPY / ^GSPC | `^CRSLDX` (Nifty 500), fallback `^NSEI` (Nifty 50) |
| Currency / thresholds | USD | INR (`min_market_cap_inr`, `min_avg_turnover_inr`) |
| Chart links | Finviz | TradingView `NSE:SYMBOL` |
| Run timing | after US close | after **NSE close, 15:30 IST** |
| Fundamentals | yfinance only | **pluggable** (yfinance + Screener.in fallback) |

The SEPA/VCP math, RS ranking, and scoring are **unchanged** — they operate on OHLCV and a few fundamental fields, which are market-agnostic.

---

## Fundamentals data sources (free)

yfinance fundamentals coverage for Indian tickers is patchy (ROE and quarterly EPS are often null). To avoid silently dropping good names, fundamentals are **pluggable** via `config.json → sepa_fundamentals.provider`:

- `yfinance` — fast, but sparse for India.
- `screener_in` — scrapes [Screener.in](https://www.screener.in) (best free Indian fundamentals: quarterly results, P&L, ROE). Pure-stdlib parser, no extra dependency.
- `yfinance_then_screener` *(default)* — yfinance first (for market cap, liquidity, sector), Screener.in fills any missing growth/ROE/margin fields.

There is also `strict_gate` (default `false`): when `false`, a **missing** fundamental is skipped rather than failing the stock — recommended for India. Set `true` to enforce Minervini's hard gates exactly as the US version does.

Other free options if you want to extend further: [NSEPython](https://pypi.org/project/nsepython/) / [jugaad-data](https://github.com/jugaad-py/jugaad-data) (NSE-published quarterly results), and freemium APIs with NSE fundamentals such as [Twelve Data](https://twelvedata.com/exchanges/XNSE), [EODHD](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds), and [Alpha Vantage](https://www.alphavantage.co/).

---

## Setup

Requires Python 3.10+.

```bash
cd minervini-stock-screener-india
cp config.example.india.json config.json   # already done; tweak thresholds if needed
chmod +x run_screener_india.sh
```

`curl_cffi` is **mandatory** (the launcher installs it) — without it Yahoo blocks yfinance as bot traffic.

### 1. (Optional) Refresh the NIFTY 500 universe

```bash
python3 build_universe_india.py
```

Fetches the current NIFTY 500 constituents and writes `tickers_india.txt` with `.NS` suffixes. **Run this on a home/office network** — NSE blocks cloud/datacenter IPs. The committed `tickers_india.txt` is a curated ~150-name seed so the screener runs immediately without this step.

### 2. Run the screener (after the NSE close, 15:30 IST)

```bash
./run_screener_india.sh        # Mac/Linux  (run_screener_india.bat on Windows)
```

First run for the seed list takes ~10–20 min; same-day re-runs are instant via cache. Output → `sepa_data_india_latest.json`.

### 3. Render the dashboard

```bash
python3 build_dashboard_india.py
```

Writes `sepa_vcp_india_watchlist.html` (open in any browser) and is the same content shown by the Cowork artifact **`sepa-vcp-india-watchlist`**.

---

## Refreshing the Cowork artifact automatically

The artifact `sepa-vcp-india-watchlist` currently shows **sample data**. To keep it live:

1. Run `sepa_screener_india.py` daily after the NSE close (cron / launchd / Task Scheduler) — it writes `sepa_data_india_latest.json` into this folder.
2. A Cowork scheduled task reads that JSON and updates the artifact (ask Claude to set this up, e.g. *"refresh the India watchlist artifact every weekday at 4:30 PM IST"*).

> yfinance is blocked inside the Cowork sandbox (NSE/Yahoo are unreachable there), which is why price fetching must run locally — exactly like the US screener.

---

## Tuning

**Every strategy setting lives in `config.json`** — the Python code reads all thresholds, weights, lookback windows, and score blends from this file. You never need to edit `.py` files to tune the strategy. Edit `config.json`, save, re-run. Key levers:

| Section | Key | Effect |
|---|---|---|
| `market` | `benchmark_ticker` | RS / regime benchmark (`^CRSLDX` or `^NSEI`) |
| `universe` | `min_market_cap_inr` | Market-cap floor in INR (default ₹2,000 cr) |
| `universe` | `min_avg_turnover_inr` | Daily traded-value floor in INR (default ₹5 cr) |
| `sepa_fundamentals` | `provider` | Fundamentals data source |
| `sepa_fundamentals` | `strict_gate` | Whether missing fundamentals fail a stock |
| `sepa_trend_template` | `within_52w_high_pct`, `recent_high_lookback_days`, `dma_*` | Trend-template thresholds and moving-average periods |
| `relative_strength` | `lookback_days`, `weights` | RS percentile windows and their blend |
| `buckets` | `at_pivot_vol_dryup_max` | Volume dry-up required for Bucket A |
| `scoring` | `weights`, `early_weights`, `fundamental_norm` | How the SEPA composite score is blended |
| `market_health` | `distribution_day_pct`, `fail_rate_amber/red` | Distribution-day and breakout-failure signal bands |

Sensible defaults ship in `config.example.india.json`; any key you omit falls back to that default, so older config files keep working.

---

## Files

```
sepa_screener_india.py        # main screener (fork of the US sepa_screener.py)
build_universe_india.py       # NIFTY 500 universe fetcher (stdlib only)
build_dashboard_india.py      # renders sepa_vcp_india_watchlist.html from the JSON
config.example.india.json     # committed default config (INR / NSE)
config.json                   # user-local config (gitignored)
tickers_india.txt             # NIFTY universe (seed; refresh with build_universe_india.py)
run_screener_india.sh / .bat  # launchers
sepa_data_india_latest.json   # screener output consumed by the dashboard (gitignored)
sepa_vcp_india_watchlist.html # the dashboard
prices_cache/                 # per-ticker daily price cache (gitignored)
```

**Not investment advice.** Verify every candidate on its chart before acting.
