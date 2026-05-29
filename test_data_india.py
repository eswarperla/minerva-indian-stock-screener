"""
Quick data-access self-test for the India screener.
====================================================
Run this FIRST on your local machine to confirm prices and fundamentals are
reachable before kicking off a full screen. Takes ~30 seconds.

  python3 test_data_india.py

Checks:
  1. yfinance + curl_cffi can fetch an NSE stock (RELIANCE.NS)
  2. yfinance can fetch the benchmark (^CRSLDX, fallback ^NSEI)
  3. Screener.in fundamentals scrape works for one name
"""
import sys

def ok(b):
    return "PASS" if b else "FAIL"


def main():
    print("=== India data self-test ===\n")

    # --- deps ---
    try:
        import yfinance as yf  # noqa
        import pandas as pd     # noqa
        print(f"[deps] yfinance {getattr(yf,'__version__','?')}  OK")
    except Exception as e:
        print(f"[deps] FAIL - install with: pip install yfinance curl_cffi pandas numpy scipy")
        print(f"       {e}")
        sys.exit(1)

    try:
        from curl_cffi import requests as cffi
        session = cffi.Session(impersonate="chrome")
        print("[deps] curl_cffi OK (browser impersonation on)")
    except ImportError:
        session = None
        print("[deps] curl_cffi MISSING - Yahoo will likely block you. "
              "Install: pip install curl_cffi")

    # --- 1. NSE stock price ---
    import yfinance as yf
    kw = dict(period="6mo", auto_adjust=True, progress=False)
    if session: kw["session"] = session
    try:
        df = yf.download("RELIANCE.NS", **kw)
        rows = 0 if df is None else len(df)
        last = None if not rows else round(float(df["Close"].iloc[-1]), 2)
        print(f"\n[1] RELIANCE.NS price fetch: {ok(rows>50)}  ({rows} rows, last ₹{last})")
    except Exception as e:
        print(f"\n[1] RELIANCE.NS price fetch: FAIL  {type(e).__name__}: {e}")

    # --- 2. benchmark ---
    got = None
    for b in ("^CRSLDX", "^NSEI"):
        try:
            bdf = yf.download(b, period="3mo", auto_adjust=True, progress=False,
                              **({"session": session} if session else {}))
            if bdf is not None and len(bdf) > 20:
                got = b
                break
        except Exception:
            pass
    print(f"[2] Benchmark fetch: {ok(got is not None)}  ({got or 'none reachable'})")

    # --- 3. Screener.in fundamentals ---
    try:
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "s", str(pathlib.Path(__file__).parent / "sepa_screener_india.py"))
        s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
        f = s.fetch_fundamentals_screener_in("RELIANCE.NS")
        if f:
            print(f"[3] Screener.in fundamentals: PASS")
            print(f"      EPS YoY={f.get('eps_q_growth')}  Sales YoY={f.get('sales_q_growth')}  "
                  f"ROE={f.get('roe')}  annual EPS gr={f.get('eps_annual_growth')}")
        else:
            print(f"[3] Screener.in fundamentals: FAIL (no data - page layout may have changed "
                  f"or symbol blocked). yfinance fundamentals will still be used.")
    except Exception as e:
        print(f"[3] Screener.in fundamentals: FAIL  {type(e).__name__}: {e}")

    print("\nIf 1 and 2 pass you're good to run ./run_screener_india.sh")
    print("If 3 fails, set config.json sepa_fundamentals.provider = \"yfinance\" for now.")


if __name__ == "__main__":
    main()
