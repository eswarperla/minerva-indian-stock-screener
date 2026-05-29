"""
Build NIFTY 500 universe -> tickers_india.txt
=============================================
Standalone helper. Run once to populate tickers_india.txt with the NIFTY 500
constituents (NSE), then re-run quarterly to refresh.

Primary source : NSE / niftyindices published CSV (ind_nifty500list.csv).
Fallback source: Wikipedia "NIFTY 500" page if the CSV is unreachable.

Tickers are written with the yfinance .NS suffix (e.g. RELIANCE.NS).

Safety: if the fetch fails or returns fewer than 300 tickers, this script
EXITS WITHOUT touching tickers_india.txt - your existing file is preserved.

ZERO external dependencies - pure Python stdlib. Run it on your LOCAL machine
(NSE blocks datacenter/cloud IPs; it works fine from a home/office connection).

Usage:
  python3 build_universe_india.py
"""

import csv
import io
import sys
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent / "tickers_india.txt"

# NSE publishes the index constituents as CSV. Mirrors differ over time; try a few.
CSV_URLS = [
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://www1.nseindia.com/content/indices/ind_nifty500list.csv",
]
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/NIFTY_500"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def fetch_url(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_symbol(sym):
    sym = (sym or "").strip().upper()
    # NSE uses '&' (e.g. M&M, J&KBANK) and '-' (BAJAJ-AUTO); yfinance keeps '-'
    # but does NOT support '&'. yfinance maps M&M -> M&M.NS actually works via
    # Yahoo using the same symbol; keep as-is, Yahoo handles & for NSE.
    if not sym:
        return None
    return sym


def fetch_nifty500_csv():
    last_err = None
    for url in CSV_URLS:
        try:
            print(f"Trying CSV: {url}")
            text = fetch_url(url)
            rows = list(csv.DictReader(io.StringIO(text)))
            syms = []
            for r in rows:
                # Column is typically 'Symbol'
                sym = r.get("Symbol") or r.get("SYMBOL") or r.get("symbol")
                sym = _clean_symbol(sym)
                if sym:
                    syms.append(sym)
            if len(syms) >= 300:
                print(f"  Got {len(syms)} symbols from CSV")
                return syms
            print(f"  Only {len(syms)} symbols parsed - trying next source")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  Failed: {last_err}")
    return None


class WikiNiftyParser(HTMLParser):
    """Extract symbols from the NIFTY 500 Wikipedia constituents table."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.sym_col = -1
        self.symbols = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and "wikitable" in (a.get("class") or ""):
            self.in_table = True
            self.sym_col = -1
        elif self.in_table:
            if tag == "tr":
                self.in_row = True
                self.row = []
            elif tag in ("td", "th"):
                self.in_cell = True
                self.cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif self.in_table:
            if tag in ("td", "th") and self.in_cell:
                self.row.append((tag, "".join(self.cell).strip()))
                self.in_cell = False
            elif tag == "tr" and self.in_row:
                self._row_done()
                self.in_row = False

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def _row_done(self):
        if any(t == "th" for t, _ in self.row):
            for i, (_, txt) in enumerate(self.row):
                if txt.strip().lower() in ("symbol", "ticker"):
                    self.sym_col = i
                    return
            return
        if self.sym_col >= 0 and len(self.row) > self.sym_col:
            sym = _clean_symbol(self.row[self.sym_col][1])
            if sym and sym.isascii() and 1 <= len(sym) <= 20:
                self.symbols.append(sym)


def fetch_nifty500_wikipedia():
    print(f"Falling back to Wikipedia: {WIKIPEDIA_URL}")
    try:
        html = fetch_url(WIKIPEDIA_URL)
    except Exception as e:
        print(f"  Wikipedia fetch failed: {type(e).__name__}: {e}")
        return None
    p = WikiNiftyParser()
    p.feed(html)
    seen = set()
    syms = [s for s in p.symbols if not (s in seen or seen.add(s))]
    print(f"  Extracted {len(syms)} symbols from Wikipedia")
    return syms if len(syms) >= 300 else None


def write_tickers_file(symbols):
    seen = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]
    today = datetime.now().strftime("%Y-%m-%d")
    header = [
        "# SEPA-VCP Screener Universe - NIFTY 500 (India / NSE)",
        "# =====================================================",
        f"# Auto-generated by build_universe_india.py on {today}",
        f"# Count: {len(symbols)} tickers",
        "#",
        "# Re-run build_universe_india.py quarterly to refresh.",
        "# One ticker per line, # for comments. .NS suffix added automatically",
        "# by the screener if omitted (yfinance NSE convention).",
        "",
    ]
    body = "\n".join(f"{s}.NS" for s in symbols)
    OUTPUT_FILE.write_text("\n".join(header) + body + "\n")
    print(f"\n[OK] Wrote {len(symbols)} tickers to {OUTPUT_FILE}")


def main():
    syms = fetch_nifty500_csv()
    if not syms:
        syms = fetch_nifty500_wikipedia()
    if not syms or len(syms) < 300:
        print("\n[FAIL] Could not fetch a complete NIFTY 500 list (>=300 symbols).",
              file=sys.stderr)
        print("  Existing tickers_india.txt was NOT modified.", file=sys.stderr)
        print("  Tip: run this on a home/office network - NSE blocks cloud IPs.",
              file=sys.stderr)
        sys.exit(1)
    write_tickers_file(syms)
    print("\nUniverse refreshed. Next: run ./run_screener_india.sh")


if __name__ == "__main__":
    main()
