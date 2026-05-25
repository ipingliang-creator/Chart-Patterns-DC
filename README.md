# Chart-Patterns-DC

Daily-bar **data collector** for the Chart-Patterns backtest universe.

This repo is deliberately dumb: it holds **no strategy code**. It fetches
the current S&P 500 constituents, pulls daily OHLCV bars from Alpaca, and
commits one parquet per symbol under `data/`. The trading bot's backtest
reads that dataset to compute win rates over a wider universe than the
~128-symbol live trading set — more symbols, more resolved trades, tighter
win-rate estimates.

Public repo on purpose: GitHub Actions minutes are free for public repos.

## What it collects

- **Source:** Alpaca `/v2/stocks/bars`, IEX feed, **split-adjusted**,
  `1Day` — the *same* feed and adjustment the trading bot uses, so the data
  pools cleanly with the bot's existing universe.
- **Symbols:** current S&P 500 (dynamic — maintained CSV first, then
  Wikipedia, then the committed `sp500_fallback.txt`) **plus** the four
  index ETFs the bot trades (SPY, QQQ, IWM, DIA).
- **Output:** `data/<SYMBOL>.parquet` — columns `o,h,l,c,v` indexed by
  timestamp (identical schema to the bot's `bars_response_to_dataframe`).
  Most-recent 400 daily bars per symbol. Plus a `data/_manifest.txt`
  summary (counts, feed, adjustment, generated date).

## Running it

- **Manually:** Actions tab → **collect** → *Run workflow*.
- **Automatically:** every Sunday 11:00 UTC (lands before the bot's Sunday
  backtest). Changed parquets are committed back to this repo.

## Secrets (required)

Set these as encrypted **repository secrets** (Settings → Secrets and
variables → Actions). Never put them in code or commit them.

| Secret | What |
|---|---|
| `ALPACA_API_KEY` | Alpaca API key id |
| `ALPACA_SECRET_KEY` | Alpaca API secret |

## Security posture — read before pointing real credentials at this

This is a **public** repo, so treat the key as compromised-by-default and
keep the blast radius tiny:

1. **Use a throwaway *paper*-account key**, never your main trading key.
   IEX market data needs only a read-only Alpaca key; a paper key is
   sufficient and can touch nothing real.
2. **Rotate / revoke the key when you're done** with this collection run.
3. **Secrets live only as encrypted Actions secrets.** They're injected
   into the `Collect bars` step as env vars and never written to disk.
4. **No fork-PR triggers.** The workflow runs *only* on
   `workflow_dispatch` and `schedule` — never `pull_request` /
   `pull_request_target` — so an outside PR can't run with these secrets
   and exfiltrate them.
5. **No strategy here.** Only generic collection of public OHLCV data, so
   even a leak exposes nothing proprietary.
