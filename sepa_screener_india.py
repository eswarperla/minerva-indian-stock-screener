"""
SEPA-VCP Daily Screener - INDIA (NSE) edition
=============================================
Mark Minervini's strict SEPA + Volatility Contraction Pattern screener,
adapted for the Indian market (NSE).

Universe: read from tickers_india.txt (Nifty 500 by default; yfinance-style
          symbols with the .NS suffix, e.g. RELIANCE.NS, TCS.NS).
Benchmark: ^CRSLDX (Nifty 500) with ^NSEI (Nifty 50) fallback.
Currency:  INR. Market-cap / turnover thresholds are in INR.
Run daily AFTER the NSE close (15:30 IST). Outputs JSON consumed by the
Cowork artifact dashboard.

Data sources (free):
  * Prices       -> yfinance (.NS tickers). Install curl_cffi to bypass Yahoo bot-block.
  * Fundamentals -> pluggable via config["sepa_fundamentals"]["provider"]:
        "yfinance"               - yfinance .info / income statements only
        "screener_in"            - Screener.in scrape only (best Indian coverage)
        "yfinance_then_screener" - (default) yfinance first, fill gaps from Screener.in
"""

import os
import sys
import json
import time
import math
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Third-party (install with: pip install yfinance pandas numpy scipy curl_cffi --break-system-packages)
import pandas as pd
import numpy as np
import yfinance as yf
from scipy.signal import find_peaks

# ---------------------------------------------------------------------------
# CONFIG (loaded from config.json - falls back to config.example.json)
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"
CONFIG_EXAMPLE_FILE = PROJECT_DIR / "config.example.json"


def _load_config():
    """Load config.json; fall back to config.example.json with a warning."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    if CONFIG_EXAMPLE_FILE.exists():
        print(f"  [WARN] {CONFIG_FILE.name} not found; using {CONFIG_EXAMPLE_FILE.name} defaults.")
        print(f"         Copy config.example.json -> config.json and tune for your setup.")
        return json.loads(CONFIG_EXAMPLE_FILE.read_text())
    raise RuntimeError(
        f"No config file found. Expected one of: {CONFIG_FILE.name} or {CONFIG_EXAMPLE_FILE.name}\n"
        f"Copy config.example.json -> config.json before running."
    )


CONFIG = _load_config()

# Derived file paths (always relative to script location - portable)
OUTPUT_JSON = PROJECT_DIR / "sepa_data_india_latest.json"
AUDIT_HISTORY_FILE = PROJECT_DIR / "sepa_audit_history.json"
SCREEN_VOL_FILE = PROJECT_DIR / "sepa_screen_volume_history.json"
FUNDAMENTALS_CACHE_FILE = PROJECT_DIR / "fundamentals_cache.json"
PRICES_CACHE_DIR = PROJECT_DIR / "prices_cache"
TICKERS_FILE = PROJECT_DIR / CONFIG["universe"]["tickers_file"]

# Market / currency (India)
CURRENCY = CONFIG.get("market", {}).get("currency", "INR")
BENCHMARK_TICKER = CONFIG.get("market", {}).get("benchmark_ticker", "^CRSLDX")
BENCHMARK_FALLBACK = CONFIG.get("market", {}).get("benchmark_fallback", "^NSEI")
BENCHMARK_LABEL = CONFIG.get("market", {}).get("benchmark_label", "NIFTY")

# yfinance + caching
BATCH_SIZE = CONFIG["yfinance"]["batch_size"]
INTER_BATCH_SLEEP = CONFIG["yfinance"]["inter_batch_sleep_seconds"]
PRICE_LOOKBACK_DAYS = CONFIG["yfinance"]["price_lookback_days"]
# INR thresholds. Keys are *_inr; we keep the same internal variable names so the
# downstream filter logic is identical to the US screener (market_cap / turnover).
MIN_MARKET_CAP = CONFIG["universe"]["min_market_cap_inr"]
MIN_AVG_DOLLAR_VOL = CONFIG["universe"]["min_avg_turnover_inr"]
FUNDAMENTALS_CACHE_TTL_DAYS = CONFIG["caching"]["fundamentals_ttl_days"]

# Fundamentals data provider: "yfinance" | "screener_in" | "yfinance_then_screener"
FUND_PROVIDER = CONFIG["sepa_fundamentals"].get("provider", "yfinance_then_screener")

# SEPA Trend Template
RS_RANK_MIN = CONFIG["sepa_trend_template"]["rs_rank_min"]
WITHIN_HIGH_PCT = CONFIG["sepa_trend_template"]["within_high_pct"]
ABOVE_LOW_MIN = CONFIG["sepa_trend_template"]["above_low_min"]

# VCP detection
BASE_MIN_WEEKS = CONFIG["vcp_detection"]["base_min_weeks"]
BASE_MAX_WEEKS = CONFIG["vcp_detection"]["base_max_weeks"]
MIN_CONTRACTIONS = CONFIG["vcp_detection"]["min_contractions"]
TIGHTENING_FACTOR = CONFIG["vcp_detection"]["tightening_factor"]
LAST_CONTRACTION_MAX = CONFIG["vcp_detection"]["last_contraction_max"]
VOL_DRYUP_MAX = CONFIG["vcp_detection"]["vol_dryup_max"]
CONTRACTION_MIN_DISTANCE = CONFIG["vcp_detection"]["contraction_min_distance"]
CONTRACTION_MIN_DEPTH = CONFIG["vcp_detection"]["contraction_min_depth"]

# Buckets
AT_PIVOT_WITHIN_PCT = CONFIG["buckets"]["at_pivot_within_pct"]
BREAKOUT_WITHIN_PCT = CONFIG["buckets"]["breakout_within_pct"]
BREAKOUT_VOL_MULT = CONFIG["buckets"]["breakout_vol_mult"]
BREAKOUT_LOOKBACK_DAYS = CONFIG["buckets"]["breakout_lookback_days"]

# Risk / stop-loss
MAX_LOSS_PCT = CONFIG.get("risk", {}).get("max_loss_pct", 0.08)

# Fundamentals (strict Minervini)
FUND_EPS_Q_MIN = CONFIG["sepa_fundamentals"]["eps_q_growth_min"]
FUND_SALES_Q_MIN = CONFIG["sepa_fundamentals"]["sales_q_growth_min"]
FUND_EPS_ANNUAL_MIN = CONFIG["sepa_fundamentals"]["eps_annual_growth_min"]
FUND_ROE_MIN = CONFIG["sepa_fundamentals"]["roe_min"]
EARNINGS_FLAG_DAYS = CONFIG["sepa_fundamentals"]["earnings_flag_days"]

# --- Additional tunables (formerly hardcoded). All have safe defaults so older
#     config files keep working. Edit config.json to change any of these. ---
_TT = CONFIG.get("sepa_trend_template", {})
WITHIN_52W_HIGH_PCT = _TT.get("within_52w_high_pct", 0.25)          # max % below 52w high
RECENT_HIGH_LOOKBACK_DAYS = _TT.get("recent_high_lookback_days", 130)  # "near recent high" window
DMA_FAST = _TT.get("dma_fast", 50)
DMA_MID = _TT.get("dma_mid", 150)
DMA_SLOW = _TT.get("dma_slow", 200)
DMA_SLOPE_LOOKBACK_DAYS = _TT.get("dma_slope_lookback_days", 22)

_RS = CONFIG.get("relative_strength", {})
RS_LOOKBACK_DAYS = _RS.get("lookback_days", [63, 126, 189, 252])   # 3/6/9/12 months
RS_WEIGHTS = _RS.get("weights", [0.4, 0.2, 0.2, 0.2])

AT_PIVOT_VOL_DRYUP_MAX = CONFIG.get("buckets", {}).get("at_pivot_vol_dryup_max", 0.8)

_SC = CONFIG.get("scoring", {})
SCORE_W = _SC.get("weights", {"rs": 0.30, "trend": 0.20, "vcp": 0.30, "distance": 0.10, "fundamentals": 0.10})
SCORE_W_EARLY = _SC.get("early_weights", {"rs": 0.40, "trend": 0.20, "distance": 0.10, "fundamentals": 0.30})
FUND_NORM = _SC.get("fundamental_norm", {"eps_q": 0.50, "sales_q": 0.40, "eps_annual": 0.50, "roe": 0.35})

_MH = CONFIG.get("market_health", {})
DIST_DAY_PCT = _MH.get("distribution_day_pct", -0.002)
DIST_WINDOW_DAYS = _MH.get("distribution_window_days", 26)
FAIL_RATE_AMBER = _MH.get("fail_rate_amber", 0.25)
FAIL_RATE_RED = _MH.get("fail_rate_red", 0.40)


# ---------------------------------------------------------------------------
# UNIVERSE
# ---------------------------------------------------------------------------
def fetch_universe():
    """Read tickers from tickers_india.txt.

    NSE tickers carry a .NS suffix for yfinance (e.g. RELIANCE.NS, BAJAJ-AUTO.NS).
    Unlike the US screener we must PRESERVE the dot in `.NS` and allow longer
    symbols, so we do NOT replace '.' with '-' and we widen the length check.
    Any line missing a market suffix gets `.NS` appended automatically.
    """
    if not TICKERS_FILE.exists():
        raise RuntimeError(
            f"Universe file not found: {TICKERS_FILE}\n"
            f"Run build_universe_india.py to generate it, or create it with one "
            f"NSE ticker per line (# for comments), e.g. RELIANCE.NS"
        )
    raw = TICKERS_FILE.read_text().splitlines()
    tickers = []
    for line in raw:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split("#")[0].strip().upper()
        if not token:
            continue
        # Ensure a market suffix; default to NSE (.NS). Keep .BO if user set it.
        if not (token.endswith(".NS") or token.endswith(".BO")):
            token = token + ".NS"
        if not token.isascii() or len(token) > 25 or "/" in token:
            print(f"  Skipping malformed ticker: {token!r}")
            continue
        tickers.append(token)
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]
    print(f"Universe loaded from {TICKERS_FILE.name}: {len(tickers)} tickers")
    if len(tickers) < 20:
        raise RuntimeError(
            f"Universe has only {len(tickers)} tickers - below safety threshold of 20. "
            f"Check {TICKERS_FILE} for syntax errors."
        )
    return tickers


# ---------------------------------------------------------------------------
# PRICE DATA (yfinance with curl_cffi browser impersonation)
# ---------------------------------------------------------------------------
def _make_yf_session():
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore
        return cffi_requests.Session(impersonate="chrome")
    except ImportError:
        return None


# ---------- Price cache (per-ticker JSON, daily TTL, crash-safe) ----------

def _ticker_cache_path(ticker):
    return PRICES_CACHE_DIR / f"{ticker}.json"


def _load_cached_prices(tickers):
    """Return {ticker: DataFrame} for tickers whose cache file is from today.
    Stale entries (different as_of_date) are ignored and will be re-fetched."""
    if not PRICES_CACHE_DIR.exists():
        return {}
    today = datetime.now().strftime("%Y-%m-%d")
    cached = {}
    for t in tickers:
        path = _ticker_cache_path(t)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
            if payload.get("as_of_date") != today:
                continue
            rows = payload.get("ohlcv") or []
            if len(rows) < 200:
                continue
            df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
            cached[t] = df
        except Exception:
            # Corrupt file - ignore, will re-fetch
            continue
    return cached


def _save_ticker_cache(ticker, df):
    """Atomically save a ticker's price data. Writes temp file then renames."""
    PRICES_CACHE_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        rows = []
        for idx, row in df.iterrows():
            try:
                close_val = row.get("Close")
                if pd.isna(close_val):
                    continue
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
                rows.append([
                    date_str,
                    float(row["Open"]) if pd.notna(row.get("Open")) else None,
                    float(row["High"]) if pd.notna(row.get("High")) else None,
                    float(row["Low"]) if pd.notna(row.get("Low")) else None,
                    float(close_val),
                    int(row["Volume"]) if pd.notna(row.get("Volume")) else 0,
                ])
            except Exception:
                continue
        payload = {"as_of_date": today, "ohlcv": rows}
        path = _ticker_cache_path(ticker)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)
    except Exception as e:
        print(f"  [WARN] failed to cache {ticker}: {e}")


def fetch_prices_batched(tickers, lookback_days=PRICE_LOOKBACK_DAYS):
    end = datetime.now()
    start = end - timedelta(days=int(lookback_days * 1.5))
    yf_version = getattr(yf, "__version__", "unknown")
    session = _make_yf_session()
    print(f"  yfinance version: {yf_version}")
    print(f"  curl_cffi session: {'YES (browser impersonation enabled)' if session else 'NO (install curl_cffi to avoid Yahoo bot-block)'}")

    # ---- Resume from same-day cache: skip tickers already fetched today ----
    cached = _load_cached_prices(tickers)
    if cached:
        print(f"  Resuming from cache: {len(cached)}/{len(tickers)} tickers already have today's data")
    result = dict(cached)
    to_fetch = [t for t in tickers if t not in cached]
    if not to_fetch:
        print(f"  All tickers already cached for today - skipping fetch entirely")
        return result

    total_batches = (len(to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE
    first_batch_diagnosed = False
    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i:i+BATCH_SIZE]
        batch_idx = i // BATCH_SIZE + 1
        batch_got = 0
        last_err = None
        success = False
        for attempt in range(3):
            try:
                kwargs = dict(start=start, end=end, group_by="ticker", auto_adjust=True,
                              progress=False, threads=False)
                if session is not None:
                    kwargs["session"] = session
                df = yf.download(batch, **kwargs)
                if df is None or df.empty:
                    last_err = "yfinance returned empty DataFrame"
                    raise RuntimeError(last_err)
                if isinstance(df.columns, pd.MultiIndex):
                    for t in batch:
                        if t in df.columns.get_level_values(0):
                            sub = df[t].dropna(how="all")
                            if len(sub) >= 200:
                                result[t] = sub
                                _save_ticker_cache(t, sub)  # incremental save - crash-safe
                                batch_got += 1
                else:
                    sub = df.dropna(how="all")
                    if len(sub) >= 200:
                        result[batch[0]] = sub
                        _save_ticker_cache(batch[0], sub)
                        batch_got = 1
                if not first_batch_diagnosed and batch_got == 0:
                    print(f"  [DIAGNOSTIC] First batch returned 0 usable rows for {batch[:5]}...")
                    print(f"  [DIAGNOSTIC] yfinance shape: {df.shape}, sample columns: {list(df.columns)[:3]}")
                    first_batch_diagnosed = True
                success = True
                break
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                wait = 2 ** attempt
                print(f"  Batch {batch_idx}/{total_batches} attempt {attempt+1} FAILED: {last_err}. Retrying in {wait}s...")
                time.sleep(wait)
        if not success:
            print(f"  Batch {batch_idx}/{total_batches} gave up after 3 attempts. Last error: {last_err}")
        time.sleep(INTER_BATCH_SLEEP)
        print(f"  Batch {batch_idx}/{total_batches}: +{batch_got} tickers (running total {len(result)}/{len(tickers)})")
    return result


# ---------------------------------------------------------------------------
# TREND TEMPLATE
# ---------------------------------------------------------------------------
def compute_trend_template(df):
    if len(df) < 220:
        return False, {}
    close = df["Close"].values
    last = close[-1]
    dma50 = pd.Series(close).rolling(DMA_FAST).mean().iloc[-1]
    dma150 = pd.Series(close).rolling(DMA_MID).mean().iloc[-1]
    dma200 = pd.Series(close).rolling(DMA_SLOW).mean().iloc[-1]
    dma200_22d_ago = pd.Series(close).rolling(DMA_SLOW).mean().iloc[-DMA_SLOPE_LOOKBACK_DAYS]
    high_52w = pd.Series(close[-252:]).max()
    low_52w = pd.Series(close[-252:]).min()
    c = {
        "above_150_and_200": last > dma150 and last > dma200,
        "dma150_gt_dma200": dma150 > dma200,
        "dma200_uptrend_22d": dma200 > dma200_22d_ago,
        "stacked_50_150_200": dma50 > dma150 > dma200,
        "above_52w_low_25pct": last >= ABOVE_LOW_MIN * low_52w,
        "within_25pct_of_52w_high": last >= (1 - WITHIN_52W_HIGH_PCT) * high_52w,
        "near_recent_high_15pct": last >= (1 - WITHIN_HIGH_PCT) * pd.Series(close[-RECENT_HIGH_LOOKBACK_DAYS:]).max(),
    }
    passed = all(c.values())
    return passed, c


def compute_rs_rank(returns_dict):
    rows = []
    for t, rets in returns_dict.items():
        if any(pd.isna(x) for x in rets):
            continue
        weighted = sum(w * r for w, r in zip(RS_WEIGHTS, rets))
        rows.append((t, weighted))
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["ticker", "score"])
    df["rank"] = df["score"].rank(pct=True).mul(98).add(1).round().astype(int)
    return dict(zip(df["ticker"], df["rank"]))


def compute_returns(prices):
    out = {}
    need = max(RS_LOOKBACK_DAYS)
    for t, df in prices.items():
        c = df["Close"].dropna().values
        if len(c) < need:
            continue
        try:
            out[t] = tuple(c[-1] / c[-d] - 1 for d in RS_LOOKBACK_DAYS)
        except (IndexError, ZeroDivisionError):
            pass
    return out


# ---------------------------------------------------------------------------
# VCP DETECTION
# ---------------------------------------------------------------------------
def detect_vcp(df):
    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    if len(close) < 50:
        return None
    base_max = BASE_MAX_WEEKS * 5
    base_min = BASE_MIN_WEEKS * 5
    # The global base high (left anchor) is used only to DELIMIT the base window,
    # not as the pivot. The pivot itself is computed below from the final contraction.
    pivot_window = close[-base_max:]
    anchor_idx_rel = int(np.argmax(pivot_window))
    anchor_abs = len(close) - base_max + anchor_idx_rel
    base_segment = close[anchor_abs:]
    if len(base_segment) < base_min:
        return None
    if len(base_segment) > base_max:
        base_segment = base_segment[-base_max:]
        base_start_abs = len(close) - base_max
    else:
        base_start_abs = anchor_abs
    base_weeks = round(len(base_segment) / 5)
    peaks_idx, _ = find_peaks(base_segment, distance=CONTRACTION_MIN_DISTANCE)
    troughs_idx, _ = find_peaks(-base_segment, distance=CONTRACTION_MIN_DISTANCE)

    # PIVOT (Minervini): the intraday HIGH of the final contraction's peak on the
    # right side of the base -- the line of least resistance -- NOT the global base
    # high. Use the last detected swing peak; smooth over a +/-1 bar window so a
    # single noisy bar doesn't set the level. Fall back to the base-window high.
    if len(peaks_idx) >= 1:
        last_peak_abs = base_start_abs + int(peaks_idx[-1])
        _lo = max(0, last_peak_abs - 1)
        _hi = min(len(high), last_peak_abs + 2)
        pivot_price = float(np.max(high[_lo:_hi]))
    else:
        pivot_price = float(np.max(high[base_start_abs:]))

    # FINAL-CONTRACTION LOW: intraday low of the last real pullback trough, used as
    # the structural stop reference. None if no trough was detected.
    if len(troughs_idx) >= 1:
        last_trough_abs = base_start_abs + int(troughs_idx[-1])
        final_contraction_low = float(low[last_trough_abs])
    else:
        final_contraction_low = None

    pivots = sorted([(i, base_segment[i], "peak") for i in peaks_idx] +
                    [(i, base_segment[i], "trough") for i in troughs_idx])
    if pivots and pivots[0][2] != "peak":
        pivots = [(0, base_segment[0], "peak")] + pivots
    if pivots and pivots[-1][2] != "trough":
        pivots.append((len(base_segment)-1, base_segment[-1], "trough"))
    contractions = []
    for i in range(0, len(pivots) - 1, 2):
        if i + 1 >= len(pivots): break
        if pivots[i][2] == "peak" and pivots[i+1][2] == "trough":
            depth = (pivots[i][1] - pivots[i+1][1]) / pivots[i][1]
            if depth > CONTRACTION_MIN_DEPTH:
                contractions.append(depth)
    if len(contractions) < MIN_CONTRACTIONS:
        return {"base_weeks": base_weeks, "num_contractions": len(contractions), "last_contraction_pct": None,
                "vol_vs_avg": None, "pivot_price": float(pivot_price),
                "final_contraction_low": final_contraction_low, "passed": False}
    tightening_ok = all(contractions[i+1] < TIGHTENING_FACTOR * contractions[i]
                        for i in range(len(contractions)-1))
    last_c = contractions[-1]
    last_c_ok = last_c <= LAST_CONTRACTION_MAX
    base_vol = vol[base_start_abs:]
    last5_vol = vol[-5:].mean() if len(vol) >= 5 else np.nan
    base_avg_vol = base_vol.mean() if len(base_vol) >= 5 else np.nan
    vol_ratio = last5_vol / base_avg_vol if base_avg_vol and not np.isnan(base_avg_vol) else None
    vol_ok = vol_ratio is not None and vol_ratio < VOL_DRYUP_MAX
    passed = tightening_ok and last_c_ok and vol_ok
    return {
        "base_weeks": base_weeks,
        "num_contractions": len(contractions),
        "last_contraction_pct": round(last_c * 100, 2),
        "vol_vs_avg": round(vol_ratio, 2) if vol_ratio else None,
        "pivot_price": float(pivot_price),
        "final_contraction_low": final_contraction_low,
        "passed": bool(passed),
        "tightening_ok": tightening_ok,
        "last_c_ok": last_c_ok,
        "vol_ok": vol_ok
    }


# ---------------------------------------------------------------------------
# FUNDAMENTALS
# ---------------------------------------------------------------------------
def _safe_eps_row(df):
    """Find the EPS row in an income statement. Tries pre-computed EPS rows first;
    falls back to computing EPS = Net Income / Diluted Shares when not present.
    Same definition the company itself uses to report EPS. Returns Series or None."""
    if df is None or df.empty:
        return None
    # First try pre-computed EPS rows (yfinance row naming varies)
    eps_candidates = ["Diluted EPS", "Basic EPS", "EPS Diluted", "EPS Basic", "EPS"]
    for key in eps_candidates:
        if key in df.index:
            series = df.loc[key]
            if series.notna().any():
                return series
    # Fallback: compute EPS = Net Income / Diluted Average Shares
    ni = _safe_row(df, "Net Income") or _safe_row(df, "Net Income Common Stockholders")
    if ni is None:
        return None
    share_candidates = [
        "Diluted Average Shares", "Basic Average Shares",
        "Diluted Average Shares Outstanding", "Basic Average Shares Outstanding",
        "Diluted Weighted Average Shares Outstanding",
    ]
    shares = None
    for key in share_candidates:
        s = _safe_row(df, key)
        if s is not None and s.notna().any() and (s > 0).any():
            shares = s
            break
    if shares is None:
        return None
    try:
        eps = ni / shares
        # Replace inf/-inf with NaN
        eps = eps.replace([float("inf"), float("-inf")], pd.NA)
        if eps.notna().any():
            return eps
    except Exception:
        pass
    return None


def _safe_row(df, key):
    if df is None or df.empty or key not in df.index:
        return None
    return df.loc[key]


def fetch_fundamentals_yfinance(ticker):
    """Fetch quarterly + annual fundamentals via yfinance MODERN API.
    Uses income_stmt / quarterly_income_stmt (not deprecated .earnings / .quarterly_earnings).
    Works for .NS tickers but Indian coverage is patchy (ROE / quarterly EPS often null).
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.info

        # Modern API: income statements (columns are most-recent-first)
        try:
            qis = tk.quarterly_income_stmt
        except Exception:
            qis = None
        try:
            ais = tk.income_stmt
        except Exception:
            ais = None

        eps_q_growth = sales_q_growth = None
        margin_expanding = None
        eps_q_accelerating = None
        eps_annual_growth = None

        # ----- Quarterly EPS growth (YoY) + acceleration -----
        eps_q = _safe_eps_row(qis)
        if eps_q is not None and len(eps_q) >= 5:
            try:
                eps_now = eps_q.iloc[0]
                eps_year_ago = eps_q.iloc[4]
                if pd.notna(eps_now) and pd.notna(eps_year_ago) and eps_year_ago != 0:
                    eps_q_growth = float((eps_now - eps_year_ago) / abs(eps_year_ago))
                if len(eps_q) >= 6:
                    eps_prev = eps_q.iloc[1]
                    eps_year_ago_prev = eps_q.iloc[5]
                    if pd.notna(eps_prev) and pd.notna(eps_year_ago_prev) and eps_year_ago_prev != 0:
                        prev_growth = float((eps_prev - eps_year_ago_prev) / abs(eps_year_ago_prev))
                        if eps_q_growth is not None:
                            eps_q_accelerating = eps_q_growth > prev_growth
            except Exception:
                pass

        # ----- Quarterly sales growth (YoY) -----
        rev_q = _safe_row(qis, "Total Revenue")
        if rev_q is not None and len(rev_q) >= 5:
            try:
                rev_now = rev_q.iloc[0]
                rev_year_ago = rev_q.iloc[4]
                if pd.notna(rev_now) and pd.notna(rev_year_ago) and rev_year_ago != 0:
                    sales_q_growth = float((rev_now - rev_year_ago) / abs(rev_year_ago))
            except Exception:
                pass

        # ----- Margin expansion (QoQ) -----
        ni_q = _safe_row(qis, "Net Income")
        if ni_q is not None and rev_q is not None and len(rev_q) >= 2 and len(ni_q) >= 2:
            try:
                m_now = ni_q.iloc[0] / rev_q.iloc[0] if rev_q.iloc[0] else None
                m_prev = ni_q.iloc[1] / rev_q.iloc[1] if rev_q.iloc[1] else None
                if m_now is not None and m_prev is not None and pd.notna(m_now) and pd.notna(m_prev):
                    margin_expanding = bool(m_now > m_prev)
            except Exception:
                pass

        # ----- Annual EPS growth -----
        eps_a = _safe_eps_row(ais)
        if eps_a is not None and len(eps_a) >= 2:
            try:
                eps_recent = eps_a.iloc[0]
                eps_prior = eps_a.iloc[1]
                if pd.notna(eps_recent) and pd.notna(eps_prior) and eps_prior != 0:
                    eps_annual_growth = float((eps_recent - eps_prior) / abs(eps_prior))
            except Exception:
                pass

        roe = info.get("returnOnEquity")
        market_cap = info.get("marketCap")
        sector = info.get("sector", "Unknown")
        name = info.get("shortName") or info.get("longName") or ticker
        avg_vol_dollar = (info.get("averageDailyVolume10Day") or 0) * (info.get("regularMarketPrice") or 0)

        # ----- Next earnings date (modern API: get_earnings_dates, fall back to calendar) -----
        earnings_within_5d = False
        try:
            ed_df = None
            if hasattr(tk, "get_earnings_dates"):
                try:
                    ed_df = tk.get_earnings_dates(limit=8)
                except Exception:
                    ed_df = None
            if ed_df is not None and not ed_df.empty:
                # Normalize timezone for comparison
                tz = ed_df.index.tz
                now_ts = pd.Timestamp.now(tz=tz) if tz is not None else pd.Timestamp.now()
                future = ed_df.index[ed_df.index > now_ts]
                if len(future) > 0:
                    next_e = future.min()
                    days_to = (next_e - now_ts).days
                    if 0 <= days_to <= EARNINGS_FLAG_DAYS:
                        earnings_within_5d = True
            else:
                # Fallback to calendar attribute (may be dict or DataFrame across versions)
                cal = tk.calendar
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date") or cal.get("earningsDate")
                    if ed:
                        if isinstance(ed, list) and ed:
                            ed = ed[0]
                        if hasattr(ed, "to_pydatetime"):
                            ed = ed.to_pydatetime()
                        if hasattr(ed, "tzinfo") and ed.tzinfo is not None:
                            ed = ed.replace(tzinfo=None)
                        days_to = (ed - datetime.now()).days
                        if 0 <= days_to <= EARNINGS_FLAG_DAYS:
                            earnings_within_5d = True
        except Exception:
            pass

        return {
            "name": name,
            "sector": sector,
            "market_cap": market_cap,
            "avg_dollar_volume": avg_vol_dollar,
            "eps_q_growth": eps_q_growth,
            "eps_q_accelerating": eps_q_accelerating,
            "sales_q_growth": sales_q_growth,
            "eps_annual_growth": eps_annual_growth,
            "roe": roe,
            "margin_expanding": margin_expanding,
            "earnings_within_5d": earnings_within_5d
        }
    except Exception as e:
        print(f"  [yfinance] fundamentals fail for {ticker}: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# FUNDAMENTALS PROVIDER 2: Screener.in (free, best Indian coverage)
# ---------------------------------------------------------------------------
# Screener.in publishes quarterly & annual financials and key ratios per company.
# No official API, but the public company page is parseable. We use only stdlib
# (urllib + html.parser) so this adds no dependency. This is BEST-EFFORT: if the
# page layout changes or a symbol 404s, we return partial/None and the caller
# falls back gracefully. Respect their site: cached for FUNDAMENTALS_CACHE_TTL_DAYS,
# one request per ticker per run, polite User-Agent.
import re
import urllib.request as _urlreq
import urllib.error as _urlerr
from html.parser import HTMLParser as _HTMLParser

_SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _num(s):
    """Parse a Screener.in numeric cell -> float or None. Handles commas, %, blanks."""
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("%", "").replace("₹", "")
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class _ScreenerTableParser(_HTMLParser):
    """Extract <table class="data-table"> blocks inside identified <section> ids.
    Builds {section_id: {"header": [...], "rows": {row_label_lower: [vals]}}}."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section_id = None
        self.in_table = False
        self.in_thead = False
        self.in_row = False
        self.in_cell = False
        self.cur_cell = []
        self.cur_row = []
        self.row_is_header = False
        self.tables = {}  # section_id -> {"header":[], "rows":{}}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.section_id = a.get("id")
        elif tag == "table" and "data-table" in (a.get("class") or ""):
            self.in_table = True
            self.tables.setdefault(self.section_id, {"header": [], "rows": {}})
        elif self.in_table:
            if tag == "thead":
                self.in_thead = True
            elif tag == "tr":
                self.in_row = True
                self.cur_row = []
                self.row_is_header = self.in_thead
            elif tag in ("td", "th"):
                self.in_cell = True
                self.cur_cell = []
                if tag == "th":
                    self.row_is_header = self.row_is_header or self.in_thead

    def handle_endtag(self, tag):
        if tag == "section":
            self.section_id = None
        elif tag == "table" and self.in_table:
            self.in_table = False
        elif self.in_table:
            if tag == "thead":
                self.in_thead = False
            elif tag in ("td", "th") and self.in_cell:
                self.cur_row.append("".join(self.cur_cell).strip())
                self.in_cell = False
            elif tag == "tr" and self.in_row:
                tbl = self.tables.get(self.section_id)
                if tbl is not None and self.cur_row:
                    if self.row_is_header and not tbl["header"]:
                        tbl["header"] = self.cur_row
                    else:
                        label = re.sub(r"[^a-z0-9 %/]", "", self.cur_row[0].lower()).strip()
                        if label:
                            tbl["rows"][label] = self.cur_row[1:]
                self.in_row = False

    def handle_data(self, data):
        if self.in_cell:
            self.cur_cell.append(data)


def _screener_fetch_html(symbol):
    """Fetch the Screener.in company page. Tries consolidated first, then standalone."""
    base = symbol.replace(".NS", "").replace(".BO", "")
    for path in (f"/company/{base}/consolidated/", f"/company/{base}/"):
        try:
            req = _urlreq.Request("https://www.screener.in" + path, headers=_SCREENER_HEADERS)
            with _urlreq.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except _urlerr.HTTPError:
            continue
        except Exception:
            continue
    return None


def _row(rows, *names):
    """Return the value list for the first matching row label (substring match)."""
    for n in names:
        n = n.lower()
        for label, vals in rows.items():
            if label.startswith(n) or n in label:
                return vals
    return None


def fetch_fundamentals_screener_in(ticker):
    """Best-effort Screener.in fundamentals. Returns the same dict shape as the
    yfinance provider (missing fields = None). Computes YoY growth from the
    quarterly table and annual EPS growth from the P&L table."""
    try:
        html = _screener_fetch_html(ticker)
        if not html:
            return None
        p = _ScreenerTableParser()
        p.feed(html)

        out = {
            "name": ticker.replace(".NS", "").replace(".BO", ""),
            "sector": "Unknown", "market_cap": None, "avg_dollar_volume": None,
            "eps_q_growth": None, "eps_q_accelerating": None, "sales_q_growth": None,
            "eps_annual_growth": None, "roe": None, "margin_expanding": None,
            "earnings_within_5d": False,
        }

        # ---- Quarterly results -> YoY EPS & Sales growth, QoQ margin ----
        q = p.tables.get("quarters", {}).get("rows", {})
        if q:
            eps_q = _row(q, "eps in rs", "eps")
            sales_q = _row(q, "sales", "revenue")
            np_q = _row(q, "net profit", "profit after tax", "pat")
            ev = [_num(x) for x in (eps_q or [])]
            sv = [_num(x) for x in (sales_q or [])]
            nv = [_num(x) for x in (np_q or [])]
            # Columns are oldest->newest on Screener.in; latest is last.
            def _yoy(vals):
                v = [x for x in vals if x is not None]
                if len(vals) >= 5 and vals[-1] is not None and vals[-5] is not None and vals[-5] != 0:
                    return (vals[-1] - vals[-5]) / abs(vals[-5])
                return None
            out["eps_q_growth"] = _yoy(ev)
            out["sales_q_growth"] = _yoy(sv)
            # acceleration: this quarter's YoY vs previous quarter's YoY
            if len(ev) >= 6 and all(ev[i] is not None for i in (-1, -2, -5, -6)) and ev[-5] and ev[-6]:
                g_now = (ev[-1] - ev[-5]) / abs(ev[-5])
                g_prev = (ev[-2] - ev[-6]) / abs(ev[-6])
                out["eps_q_accelerating"] = g_now > g_prev
            # margin expanding: NP/Sales latest vs previous quarter
            if len(nv) >= 2 and len(sv) >= 2 and nv[-1] is not None and nv[-2] is not None \
               and sv[-1] and sv[-2]:
                out["margin_expanding"] = (nv[-1] / sv[-1]) > (nv[-2] / sv[-2])

        # ---- Annual P&L -> annual EPS growth ----
        pl = p.tables.get("profit-loss", {}).get("rows", {})
        if pl:
            eps_a = [_num(x) for x in (_row(pl, "eps in rs", "eps") or [])]
            if len(eps_a) >= 2 and eps_a[-1] is not None and eps_a[-2] is not None and eps_a[-2] != 0:
                out["eps_annual_growth"] = (eps_a[-1] - eps_a[-2]) / abs(eps_a[-2])

        # ---- Ratios -> ROE (Screener reports as %, store as fraction) ----
        rt = p.tables.get("ratios", {}).get("rows", {})
        if rt:
            roe_v = [_num(x) for x in (_row(rt, "return on equity", "roe") or [])]
            roe_v = [x for x in roe_v if x is not None]
            if roe_v:
                out["roe"] = roe_v[-1] / 100.0

        return out
    except Exception as e:
        print(f"  [screener.in] fundamentals fail for {ticker}: {type(e).__name__}: {e}")
        return None


def _merge_fund(primary, secondary):
    """Fill None fields of `primary` from `secondary`. Returns primary."""
    if primary is None:
        return secondary
    if secondary is None:
        return primary
    for k, v in secondary.items():
        if primary.get(k) in (None, "Unknown") and v not in (None, "Unknown"):
            primary[k] = v
    return primary


def fetch_fundamentals(ticker):
    """Provider dispatcher. Honors config sepa_fundamentals.provider:
       yfinance | screener_in | yfinance_then_screener (default)."""
    if FUND_PROVIDER == "yfinance":
        return fetch_fundamentals_yfinance(ticker)
    if FUND_PROVIDER == "screener_in":
        return fetch_fundamentals_screener_in(ticker)
    # hybrid: yfinance is fast & has market_cap/liquidity/sector; Screener fills gaps
    yf_f = fetch_fundamentals_yfinance(ticker)
    needs_fill = (yf_f is None) or any(
        yf_f.get(k) is None for k in
        ("eps_q_growth", "sales_q_growth", "eps_annual_growth", "roe", "margin_expanding")
    )
    if needs_fill:
        sc_f = fetch_fundamentals_screener_in(ticker)
        return _merge_fund(yf_f, sc_f)
    return yf_f


def load_fundamentals_cache():
    if not FUNDAMENTALS_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(FUNDAMENTALS_CACHE_FILE.read_text())
    except Exception as e:
        print(f"  Fundamentals cache load failed ({e}); starting fresh")
        return {}


def save_fundamentals_cache(cache):
    try:
        FUNDAMENTALS_CACHE_FILE.write_text(json.dumps(cache, indent=2, default=str))
    except Exception as e:
        print(f"  Fundamentals cache save failed: {e}")


def get_fundamentals_cached_or_fresh(ticker, cache):
    cached = cache.get(ticker)
    if cached:
        try:
            fetched = datetime.fromisoformat(cached["fetched_at"])
            age_days = (datetime.now() - fetched).days
            if age_days < FUNDAMENTALS_CACHE_TTL_DAYS:
                return cached["data"], "cached"
        except Exception:
            pass
    f = fetch_fundamentals(ticker)
    if f is not None:
        cache[ticker] = {"fetched_at": datetime.now().isoformat(timespec="seconds"), "data": f}
    return f, ("fresh" if f else "fail")


def fundamentals_pass(f):
    """Minervini hard gates: EPS growth, sales growth, annual EPS growth, ROE,
    margin expansion. EPS acceleration is a soft score boost, not a gate.

    India data note: yfinance/Screener coverage is patchy, so the gate has two
    modes (config sepa_fundamentals.strict_gate):
      * strict_gate = true  -> a MISSING field FAILS the stock (US behaviour).
      * strict_gate = false -> (default) a missing field is SKIPPED; we only
        reject when the field is present AND below threshold. This stops good
        names being silently dropped on null fundamentals."""
    if f is None:
        return False
    strict = CONFIG["sepa_fundamentals"].get("strict_gate", False)

    def gate(val, minimum):
        if val is None:
            return False if strict else True   # missing: fail if strict, else pass
        return val >= minimum

    try:
        if not gate(f.get("eps_q_growth"), FUND_EPS_Q_MIN): return False
        if not gate(f.get("sales_q_growth"), FUND_SALES_Q_MIN): return False
        if not gate(f.get("eps_annual_growth"), FUND_EPS_ANNUAL_MIN): return False
        if not gate(f.get("roe"), FUND_ROE_MIN): return False
        me = f.get("margin_expanding")
        if me is None:
            if strict: return False
        elif not me:
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# BUCKET CLASSIFICATION
# ---------------------------------------------------------------------------
def classify_bucket(df, vcp):
    if vcp is None: return None
    close = df["Close"].values
    vol = df["Volume"].values
    last = close[-1]
    pivot = vcp["pivot_price"]
    dist_pct = (last - pivot) / pivot
    vol50 = pd.Series(vol).rolling(50).mean().iloc[-1]
    for d in range(1, BREAKOUT_LOOKBACK_DAYS + 1):
        if close[-d] > pivot and close[-d - 1] <= pivot and vol[-d] >= BREAKOUT_VOL_MULT * vol50:
            if dist_pct <= BREAKOUT_WITHIN_PCT:
                return ("B", dist_pct * 100, d)
            else:
                break
    for d in range(2, BREAKOUT_LOOKBACK_DAYS + 4):
        if d >= len(close): break
        if close[-d] > pivot and last < pivot and (pivot - last) / pivot > 0.03:
            return ("D", dist_pct * 100, d)
    if vcp["passed"] and -AT_PIVOT_WITHIN_PCT <= dist_pct <= 0 and (vol[-5:].mean() / vol50 < AT_PIVOT_VOL_DRYUP_MAX):
        return ("A", dist_pct * 100, None)
    if dist_pct < -AT_PIVOT_WITHIN_PCT and vcp["num_contractions"] >= 1:
        return ("C", dist_pct * 100, None)
    return None


# ---------------------------------------------------------------------------
# SEPA SCORE
# ---------------------------------------------------------------------------
def compute_sepa_score(rs_rank, trend_pass_count, vcp, dist_pct, fund_score):
    rs_norm = min(rs_rank, 99)
    trend_norm = (trend_pass_count / 7) * 100
    vcp_tightness = 0
    if vcp and vcp.get("last_contraction_pct") is not None:
        vcp_tightness = max(0, min(100, (15 - vcp["last_contraction_pct"]) / 10 * 100))
    if vcp and vcp.get("vol_vs_avg") is not None:
        vol_score = max(0, min(100, (0.7 - vcp["vol_vs_avg"]) / 0.4 * 100))
        vcp_tightness = (vcp_tightness + vol_score) / 2
    dist_score = max(0, min(100, 100 - abs(dist_pct) * 10))
    fund_norm = fund_score * 100
    score = (SCORE_W["rs"] * rs_norm + SCORE_W["trend"] * trend_norm + SCORE_W["vcp"] * vcp_tightness +
             SCORE_W["distance"] * dist_score + SCORE_W["fundamentals"] * fund_norm)
    return int(round(score))


def fundamental_score(f):
    """Composite fundamental quality 0-1. Includes a +acceleration boost since
    eps_q_accelerating is no longer a hard gate."""
    if f is None: return 0
    parts = []
    if f.get("eps_q_growth") is not None: parts.append(min(1, max(0, f["eps_q_growth"] / FUND_NORM["eps_q"])))
    if f.get("sales_q_growth") is not None: parts.append(min(1, max(0, f["sales_q_growth"] / FUND_NORM["sales_q"])))
    if f.get("eps_annual_growth") is not None: parts.append(min(1, max(0, f["eps_annual_growth"] / FUND_NORM["eps_annual"])))
    if f.get("roe") is not None: parts.append(min(1, max(0, f["roe"] / FUND_NORM["roe"])))
    if f.get("margin_expanding"): parts.append(1.0)
    # Acceleration boost: full credit if accelerating, neutral if not
    if f.get("eps_q_accelerating"): parts.append(1.0)
    return sum(parts) / len(parts) if parts else 0


# ---------------------------------------------------------------------------
# DISTRIBUTION DAYS & MARKET REGIME
# ---------------------------------------------------------------------------
def _flatten_to_1d(arr):
    """Safely coerce a possibly 2D column (e.g. shape (N,1) from MultiIndex yfinance result)
    into a 1D numpy array so pd.Series().rolling() doesn't blow up."""
    a = np.asarray(arr)
    if a.ndim > 1:
        a = a.squeeze()
        if a.ndim > 1:
            a = a[:, 0]
    return a


def compute_distribution_days(spx_df):
    if spx_df is None or len(spx_df) < 30: return 0
    w = DIST_WINDOW_DAYS
    closes = _flatten_to_1d(spx_df["Close"].values)[-w:]
    vols = _flatten_to_1d(spx_df["Volume"].values)[-w:]
    count = 0
    for i in range(1, len(closes)):
        pct = (closes[i] - closes[i-1]) / closes[i-1]
        if pct < DIST_DAY_PCT and vols[i] > vols[i-1]:
            count += 1
    return count


def compute_market_regime(spx_df):
    if spx_df is None or len(spx_df) < 220:
        return {"regimeLight": "amber", "regimeLabel": "Unknown", "regimeSub": "Insufficient data"}
    close = _flatten_to_1d(spx_df["Close"].values)
    dma50 = pd.Series(close).rolling(50).mean().iloc[-1]
    dma200 = pd.Series(close).rolling(200).mean().iloc[-1]
    last = float(close[-1])
    if last > dma50 and last > dma200 and dma50 > dma200:
        return {"regimeLight": "green", "regimeLabel": "Confirmed Uptrend", "regimeSub": f"{BENCHMARK_LABEL} > 50/200-DMA"}
    elif last > dma200:
        return {"regimeLight": "amber", "regimeLabel": "Uptrend Under Pressure", "regimeSub": "Below 50-DMA"}
    else:
        return {"regimeLight": "red", "regimeLabel": "Correction", "regimeSub": f"{BENCHMARK_LABEL} < 200-DMA"}


# ---------------------------------------------------------------------------
# PERSISTENCE
# ---------------------------------------------------------------------------
def load_json(path, default):
    if Path(path).exists():
        try: return json.loads(Path(path).read_text())
        except Exception: return default
    return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str))


def update_audit_history(d_bucket_stocks, today_str):
    hist = load_json(AUDIT_HISTORY_FILE, [])
    existing_keys = {(h["ticker"], h["breakoutDate"]) for h in hist}
    for s in d_bucket_stocks:
        bo_date = s.get("breakoutDate") or today_str
        key = (s["ticker"], bo_date)
        if key not in existing_keys:
            hist.append({
                "ticker": s["ticker"],
                "breakoutDate": bo_date,
                "breakoutPrice": s.get("pivotPrice"),
                "failureDate": today_str,
                "failurePct": s.get("distFromPivotPct"),
                "currentClose": s.get("close"),
                "currentVsBreakoutPct": s.get("distFromPivotPct")
            })
    hist = hist[-200:]
    save_json(AUDIT_HISTORY_FILE, hist)
    return hist


def compute_failed_rate_30d(hist):
    cutoff = datetime.now() - timedelta(days=30)
    recent_fails = [h for h in hist if datetime.fromisoformat(h["failureDate"][:10]) >= cutoff]
    return len(recent_fails)


def update_screen_volume(total_today):
    vol_hist = load_json(SCREEN_VOL_FILE, [])
    today = datetime.now().strftime("%Y-%m-%d")
    if vol_hist and vol_hist[-1]["date"] == today:
        vol_hist[-1]["count"] = total_today
    else:
        vol_hist.append({"date": today, "count": total_today})
    vol_hist = vol_hist[-90:]
    save_json(SCREEN_VOL_FILE, vol_hist)
    return [v["count"] for v in vol_hist[-60:]]


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print(f"=== SEPA-VCP Screener [INDIA/NSE]: {datetime.now().isoformat()} ===")
    print(f"  Benchmark={BENCHMARK_TICKER} (fallback {BENCHMARK_FALLBACK}) | Currency={CURRENCY} | Fundamentals={FUND_PROVIDER}")
    tickers = fetch_universe()
    # Stage counters - tracks where stocks drop out of the funnel
    stats = {
        "universe_size": len(tickers),
        "prices_fetched": 0,
        "trend_passed": 0,
        "vcp_detected": 0,
        "vcp_passed": 0,
        "bucket_classified": 0,
        "fundamentals_passed": 0,
        "size_liquidity_passed": 0,
        "final_per_bucket": {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
    }

    print("\n[1/5] Fetching price data...")
    prices = fetch_prices_batched(tickers)
    print(f"  Got prices for {len(prices)}/{len(tickers)} tickers")
    stats["prices_fetched"] = len(prices)
    if len(prices) < max(20, len(tickers) // 4):
        raise RuntimeError(
            f"Price fetch returned only {len(prices)}/{len(tickers)} tickers - "
            f"likely yfinance throttling or network issue. Not safe to produce a watchlist."
        )

    print("\n[2/5] Computing RS ranks...")
    returns = compute_returns(prices)
    rs_ranks = compute_rs_rank(returns)

    print("\n[3/5] Trend Template pre-filter (cheap)...")
    trend_passers = []
    for ticker, df in prices.items():
        try:
            trend_passed, trend_breakdown = compute_trend_template(df)
            if not trend_passed: continue
            rs = rs_ranks.get(ticker, 0)
            if rs < RS_RANK_MIN: continue
            trend_passers.append((ticker, df, trend_breakdown, rs))
        except Exception as e:
            print(f"  Trend check error {ticker}: {e}")
    trend_pass_count_total = len(trend_passers)
    stats["trend_passed"] = trend_pass_count_total
    print(f"  {trend_pass_count_total} tickers passed Trend Template + RS - fetching fundamentals only for these")

    print(f"\n[4/5] Fundamentals (TTL {FUNDAMENTALS_CACHE_TTL_DAYS}d)...")
    fund_cache = load_fundamentals_cache()
    cache_hits = cache_misses = cache_fails = 0
    fundamentals_by_ticker = {}
    for ticker, _, _, _ in trend_passers:
        f, source = get_fundamentals_cached_or_fresh(ticker, fund_cache)
        if source == "cached": cache_hits += 1
        elif source == "fresh": cache_misses += 1
        else: cache_fails += 1
        fundamentals_by_ticker[ticker] = f
    save_fundamentals_cache(fund_cache)
    print(f"  cache hits={cache_hits}  fresh fetches={cache_misses}  failures={cache_fails}")

    print("\n[5/5] VCP detection + classification + scoring...")
    candidates = []
    for ticker, df, trend_breakdown, rs in trend_passers:
        try:
            vcp = detect_vcp(df)
            if vcp is None:
                # Bucket E ("Developing - Too Early"): trend+RS pass, but base hasn't
                # formed yet. Surface stocks that are at/near a fresh pivot for monitoring.
                try:
                    close = df["Close"].values
                    base_max = BASE_MAX_WEEKS * 5
                    recent = close[-base_max:]
                    e_pivot = float(recent.max())
                    e_pivot_idx = int(np.argmax(recent))
                    e_days_since = base_max - 1 - e_pivot_idx
                    e_last = float(df["Close"].iloc[-1])
                    e_dist = (e_last - e_pivot) / e_pivot * 100
                    if e_days_since < (BASE_MIN_WEEKS * 5) and abs(e_dist) < 5:
                        f = fundamentals_by_ticker.get(ticker)
                        if f is None: continue
                        if f.get("market_cap") and f["market_cap"] < MIN_MARKET_CAP: continue
                        if f.get("avg_dollar_volume") and f["avg_dollar_volume"] < MIN_AVG_DOLLAR_VOL: continue
                        trend_passed_count = sum(1 for v in trend_breakdown.values() if v)
                        fund_score = fundamental_score(f)
                        # Score for E: no VCP component; weight RS + trend + distance + fundamentals
                        e_score = int(round(SCORE_W_EARLY["rs"] * min(rs,99) +
                                            SCORE_W_EARLY["trend"] * (trend_passed_count/7)*100 +
                                            SCORE_W_EARLY["distance"] * max(0, 100 - abs(e_dist)*10) +
                                            SCORE_W_EARLY["fundamentals"] * fund_score * 100))
                        sparkline = df["Close"].tail(60).round(2).tolist()
                        candidates.append({
                            "ticker": ticker, "name": f["name"], "sector": f["sector"], "bucket": "E",
                            "sepaScore": e_score, "rsRank": int(rs),
                            "pivotPrice": round(e_pivot, 2), "close": round(e_last, 2),
                            "distFromPivotPct": round(e_dist, 2),
                            "baseWeeks": round(e_days_since / 5, 1),
                            "numContractions": 0, "lastContractionPct": None, "volVsAvg": None,
                            "epsGrowthAnnual": round(f["eps_annual_growth"], 3) if f["eps_annual_growth"] is not None else None,
                            "roe": round(f["roe"], 3) if f["roe"] is not None else None,
                            "marginExpanding": bool(f.get("margin_expanding")),
                            "earningsWithin5d": bool(f.get("earnings_within_5d")),
                            "isNewToday": False, "sparkline": sparkline,
                            "daysSincePivot": e_days_since,
                            # No formed base yet -> no valid pivot/stop. Risk is N/A
                            # until the stock develops a proper VCP (bucket A/B/C).
                            "stopPrice": None, "riskPct": None
                        })
                        stats["bucket_classified"] += 1
                        print(f"  {ticker} -> Bucket E (too early, {e_days_since}d since pivot)")
                except Exception:
                    pass
                continue
            stats["vcp_detected"] += 1
            if vcp.get("passed"): stats["vcp_passed"] += 1
            bucket_result = classify_bucket(df, vcp)
            if bucket_result is None: continue
            stats["bucket_classified"] += 1
            bucket, dist_pct, days_since_bo = bucket_result
            f = fundamentals_by_ticker.get(ticker)
            if bucket in ("A", "B") and not fundamentals_pass(f): continue
            if bucket == "A" and not vcp["passed"]: continue
            if f is None: continue
            if bucket in ("A", "B"): stats["fundamentals_passed"] += 1
            if f.get("market_cap") and f["market_cap"] < MIN_MARKET_CAP: continue
            if f.get("avg_dollar_volume") and f["avg_dollar_volume"] < MIN_AVG_DOLLAR_VOL: continue
            stats["size_liquidity_passed"] += 1
            trend_passed_count = sum(1 for v in trend_breakdown.values() if v)
            fund_score = fundamental_score(f)
            sepa_score = compute_sepa_score(rs, trend_passed_count, vcp, dist_pct, fund_score)
            sparkline = df["Close"].tail(60).round(2).tolist()
            stock = {
                "ticker": ticker,
                "name": f["name"],
                "sector": f["sector"],
                "bucket": bucket,
                "sepaScore": sepa_score,
                "rsRank": int(rs),
                "pivotPrice": round(vcp["pivot_price"], 2),
                "close": round(float(df["Close"].iloc[-1]), 2),
                "distFromPivotPct": round(dist_pct, 2),
                "baseWeeks": vcp["base_weeks"],
                "numContractions": vcp["num_contractions"],
                "lastContractionPct": vcp["last_contraction_pct"],
                "volVsAvg": vcp["vol_vs_avg"],
                "epsGrowthAnnual": round(f["eps_annual_growth"], 3) if f["eps_annual_growth"] is not None else None,
                "roe": round(f["roe"], 3) if f["roe"] is not None else None,
                "marginExpanding": bool(f.get("margin_expanding")),
                "earningsWithin5d": bool(f.get("earnings_within_5d")),
                "isNewToday": False,
                "sparkline": sparkline
            }
            # Technical stop = intraday low of the final contraction. riskPct is the
            # distance from the pivot (buy point) down to that stop. Per Minervini,
            # cap risk at MAX_LOSS_PCT -- the dashboard flags riskPct above the cap.
            fc_low = vcp.get("final_contraction_low")
            pivot = vcp["pivot_price"]
            if fc_low is not None and pivot and fc_low < pivot:
                stock["stopPrice"] = round(fc_low, 2)
                stock["riskPct"] = round((pivot - fc_low) / pivot * 100, 2)
            else:
                stock["stopPrice"] = None
                stock["riskPct"] = None
            if days_since_bo is not None:
                stock["daysSinceBreakout"] = days_since_bo
            candidates.append(stock)
            print(f"  {ticker} -> Bucket {bucket} (SEPA {sepa_score}, RS {rs})")
        except Exception as e:
            print(f"  {ticker} error: {e}")

    prior = load_json(OUTPUT_JSON, {"stocks": []})
    prior_tickers = {(s["ticker"], s["bucket"]) for s in prior.get("stocks", [])}
    for c in candidates:
        if (c["ticker"], c["bucket"]) not in prior_tickers:
            c["isNewToday"] = True

    print("\n[wrap-up] Market regime + audit history...")
    # India benchmark: Nifty 500 (^CRSLDX) preferred, Nifty 50 (^NSEI) fallback.
    spx_df = prices.get(BENCHMARK_TICKER) or prices.get(BENCHMARK_FALLBACK)
    if spx_df is None:
        session = _make_yf_session()
        for bench in (BENCHMARK_TICKER, BENCHMARK_FALLBACK):
            try:
                kw = dict(period="1y", progress=False, auto_adjust=True)
                if session: kw["session"] = session
                spx_df = yf.download(bench, **kw)
                if spx_df is not None and isinstance(spx_df.columns, pd.MultiIndex):
                    spx_df.columns = spx_df.columns.get_level_values(0)
                if spx_df is not None and not spx_df.empty:
                    print(f"  Benchmark loaded: {bench}")
                    break
            except Exception as e:
                print(f"  [WARN] benchmark {bench} download failed: {e}")
                spx_df = None
    try:
        regime = compute_market_regime(spx_df)
    except Exception as e:
        print(f"  [WARN] Market regime calc failed: {e}")
        regime = {"regimeLight": "amber", "regimeLabel": "Unknown", "regimeSub": "Calc error"}
    try:
        dist_days = compute_distribution_days(spx_df)
    except Exception as e:
        print(f"  [WARN] Distribution days calc failed: {e}")
        dist_days = 0

    buckets = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for c in candidates: buckets[c["bucket"]] += 1
    stats["final_per_bucket"] = buckets
    new_today = sum(1 for c in candidates if c["isNewToday"])
    avg_sepa = int(round(sum(c["sepaScore"] for c in candidates) / len(candidates))) if candidates else 0

    today_str = datetime.now().strftime("%Y-%m-%d")
    d_stocks = [c for c in candidates if c["bucket"] == "D"]
    audit_hist = update_audit_history(d_stocks, today_str)
    failed_count_30d = compute_failed_rate_30d(audit_hist)
    total_bo_30d = max(failed_count_30d + 10, 20)
    fail_rate = failed_count_30d / total_bo_30d if total_bo_30d else 0

    screen_vol_60d = update_screen_volume(len(candidates))

    from collections import Counter
    sector_counter = Counter(c["sector"] for c in candidates)
    total_cand = max(len(candidates), 1)
    sector_breakdown = [
        {"sector": k, "count": v, "pct": round(v / total_cand * 100, 1)}
        for k, v in sector_counter.most_common()
    ]

    dist_light = "green" if dist_days < 3 else ("amber" if dist_days < 5 else "red")
    dist_sub = "Healthy" if dist_days < 3 else ("Caution band" if dist_days < 5 else "Under distribution")
    fail_light = "green" if fail_rate < FAIL_RATE_AMBER else ("amber" if fail_rate < FAIL_RATE_RED else "red")
    fail_sub = ("Normal regime" if fail_rate < FAIL_RATE_AMBER
                else "Mixed regime - reduce size" if fail_rate < FAIL_RATE_RED
                else "Hostile to breakouts - pause new entries")

    universe_health_pct = round(trend_pass_count_total / max(len(prices), 1) * 100, 1)

    output = {
        "asOf": today_str,
        "market": "IN",
        "currency": CURRENCY,
        "benchmarkLabel": BENCHMARK_LABEL,
        "fundamentalsProvider": FUND_PROVIDER,
        "marketRegime": {
            "universeHealthPct": universe_health_pct,
            "regimeLight": regime["regimeLight"],
            "regimeLabel": regime["regimeLabel"],
            "regimeSub": regime["regimeSub"],
            "distributionDays25d": dist_days,
            "distLight": dist_light,
            "distSub": dist_sub,
            "avgSepaScore": avg_sepa,
            "failedBreakoutRate30d": round(fail_rate, 2),
            "failLight": fail_light,
            "failSub": fail_sub,
            "screenVolume60d": screen_vol_60d
        },
        "buckets": buckets,
        "maxLossPct": round(MAX_LOSS_PCT * 100, 2),
        "newToday": new_today,
        "sectorBreakdown": sector_breakdown,
        "stocks": candidates,
        "auditHistory": audit_hist[-30:],
        "funnel": stats
    }
    save_json(OUTPUT_JSON, output)
    print(f"\n[OK] Wrote {len(candidates)} candidates to {OUTPUT_JSON}")
    print(f"  Funnel: universe={stats['universe_size']} -> prices={stats['prices_fetched']} -> trend={stats['trend_passed']} -> vcp={stats['vcp_detected']} (passed={stats['vcp_passed']}) -> classified={stats['bucket_classified']} -> final={len(candidates)}")
    print(f"  Buckets: A={buckets['A']} B={buckets['B']} C={buckets['C']} D={buckets['D']} E={buckets['E']}")
    print(f"  Regime: {regime['regimeLabel']} | Dist days: {dist_days} | Fail rate: {fail_rate:.0%}")


def write_error_state(exc):
    try:
        tb = traceback.format_exc()
        err = {
            "error": True,
            "errorMessage": f"{type(exc).__name__}: {exc}",
            "errorTimestamp": datetime.now().isoformat(timespec="seconds"),
            "errorTraceback": tb,
            "asOf": datetime.now().strftime("%Y-%m-%d"),
            "marketRegime": {"universeHealthPct": 0, "regimeLight": "red", "regimeLabel": "Screener Error",
                "regimeSub": "Check logs", "distributionDays25d": 0, "distLight": "red", "distSub": "-",
                "avgSepaScore": 0, "failedBreakoutRate30d": 0, "failLight": "red", "failSub": "-",
                "screenVolume60d": []},
            "buckets": {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
            "newToday": 0, "sectorBreakdown": [], "stocks": [], "auditHistory": []
        }
        OUTPUT_JSON.write_text(json.dumps(err, indent=2, default=str))
        print(f"\n[FAIL] Error state written to {OUTPUT_JSON}")
    except Exception as inner:
        print(f"FATAL: could not write error state: {inner}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        write_error_state(e)
        sys.exit(1)
