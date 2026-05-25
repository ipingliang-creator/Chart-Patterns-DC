"""Daily-bar collector for the Chart-Patterns backtest universe.

Standalone — holds NO strategy code. It just:
  1. fetches the current S&P 500 constituents (dynamic, with a committed
     fallback list),
  2. pulls daily OHLCV bars from Alpaca — IEX feed, split-adjusted, the
     *same* feed/adjustment the trading bot uses, so the expanded
     win rates pool cleanly with the existing universe,
  3. writes one parquet per symbol under data/ (schema: o,h,l,c,v indexed
     by timestamp — identical to the bot's bars_response_to_dataframe).

Run by GitHub Actions (manual dispatch + weekly schedule). Credentials
come from the ALPACA_API_KEY / ALPACA_SECRET_KEY repo secrets — use a
throwaway *paper* account key, and rotate it when done.
"""

from __future__ import annotations

import io
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

DATA_URL = "https://data.alpaca.markets"
FEED = "iex"            # match the bot's free IEX feed
ADJUSTMENT = "split"    # match the bot's split adjustment
SYMBOL_BATCH = 100      # symbols per multi-symbol request
PAGE_LIMIT = 10000
HISTORY_BARS = 400      # most-recent N daily bars kept per symbol

OUT_DIR = Path("data")
FALLBACK = Path("sp500_fallback.txt")

# The trading bot also trades these index ETFs (not S&P 500 members, so
# no dynamic source lists them). Always collect them so the dataset is a
# clean superset of the bot's universe.
ALWAYS_INCLUDE = ["SPY", "QQQ", "IWM", "DIA"]

SP500_CSV = (
    "https://raw.githubusercontent.com/datasets/"
    "s-and-p-500-companies/main/data/constituents.csv"
)
SP500_WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _normalize(sym: str) -> str:
    # Alpaca uses dotted class shares (e.g. BRK.B); sources vary (BRK-B).
    return sym.strip().upper().replace("-", ".").replace("/", ".")


def sp500_symbols() -> list[str]:
    """Current S&P 500 tickers — maintained CSV first, then Wikipedia,
    then the committed fallback. Needs ≥400 to trust a dynamic source."""
    for name, fetch in (("csv", _from_csv), ("wiki", _from_wiki)):
        try:
            syms = fetch()
            if len(syms) >= 400:
                print(f"symbols: {len(syms)} from {name}")
                return syms
            print(f"symbols: {name} returned only {len(syms)}, trying next")
        except Exception as exc:  # noqa: BLE001 — any failure → next source
            print(f"symbols: {name} source failed: {exc}")
    syms = [_normalize(s) for s in FALLBACK.read_text().split() if s.strip()]
    print(f"symbols: {len(syms)} from committed fallback")
    return syms


def _from_csv() -> list[str]:
    r = httpx.get(SP500_CSV, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    return sorted({_normalize(s) for s in df["Symbol"].astype(str)})


def _from_wiki() -> list[str]:
    df = pd.read_html(SP500_WIKI)[0]
    return sorted({_normalize(s) for s in df["Symbol"].astype(str)})


def fetch_bars(symbols: list[str]) -> dict[str, list[dict[str, object]]]:
    """Batched, paged daily bars. Mirrors the bot's daily_bars exactly
    (1Day, IEX, split-adjusted, ascending) so the data is identical."""
    start = (date.today() - timedelta(days=800)).isoformat()
    headers = {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    }
    combined: dict[str, list[dict[str, object]]] = {}
    batches = [
        symbols[i : i + SYMBOL_BATCH]
        for i in range(0, len(symbols), SYMBOL_BATCH)
    ]
    with httpx.Client(headers=headers, timeout=60.0) as client:
        for n, batch in enumerate(batches, start=1):
            token: str | None = None
            while True:
                params: dict[str, str | int] = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "limit": PAGE_LIMIT,
                    "feed": FEED,
                    "adjustment": ADJUSTMENT,
                    "start": start,
                    "sort": "asc",
                }
                if token:
                    params["page_token"] = token
                r = client.get(f"{DATA_URL}/v2/stocks/bars", params=params)
                r.raise_for_status()
                page = r.json()
                for sym, bars in (page.get("bars") or {}).items():
                    combined.setdefault(sym, []).extend(bars)
                token = page.get("next_page_token")
                if not token:
                    break
            print(f"bars: batch {n}/{len(batches)} done ({len(batch)} symbols)")
    return combined


def write_parquets(bars_by_symbol: dict[str, list[dict[str, object]]]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for sym, bars in bars_by_symbol.items():
        if not bars:
            continue
        df = pd.DataFrame(bars[-HISTORY_BARS:])
        df.index = pd.to_datetime(df["t"])
        df[["o", "h", "l", "c", "v"]].to_parquet(OUT_DIR / f"{_normalize(sym)}.parquet")
        written += 1
    return written


def main() -> int:
    symbols = sorted(set(sp500_symbols()) | {_normalize(s) for s in ALWAYS_INCLUDE})
    bars = fetch_bars(symbols)
    written = write_parquets(bars)
    missing = [s for s in symbols if not bars.get(s)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "_manifest.txt").write_text(
        f"generated_utc: {date.today().isoformat()}\n"
        f"requested: {len(symbols)}\n"
        f"written: {written}\n"
        f"missing: {len(missing)}\n"
        f"feed: {FEED}\nadjustment: {ADJUSTMENT}\nhistory_bars: {HISTORY_BARS}\n"
    )
    print(f"wrote {written}/{len(symbols)} parquet files to {OUT_DIR}/")
    if missing:
        print(f"no bars for {len(missing)}: {', '.join(missing[:20])}"
              + (" ..." if len(missing) > 20 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
