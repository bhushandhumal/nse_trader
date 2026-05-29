"""
Three-Supertrend pre-market ticker screener.

Fetches the current Nifty 200 constituent list from NSE, then pulls
75 days of daily OHLCV for each ticker, computes ADX(14) and ATR%(14),
filters by thresholds, sorts by ADX, and prints a TICKERS= line ready
to paste into .env.

Run before 9:15 AM each morning:
    python -m src.strategies.three_supertrends_screener
"""

import io
import sys
import time
import datetime as dt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from src.session import load_session
from src.data import get_instruments, fetch_ohlc, instrument_lookup

# ── Config ────────────────────────────────────────────────────────────────────
ADX_MIN      = 25    # minimum ADX to consider trending
ATR_PCT_MIN  = 1.0   # minimum ATR as % of close (filters out sleepy stocks)
TOP_N        = 50    # max tickers to output
LOOKBACK     = 75    # calendar days of daily data (~50 trading days, needed for ADX(14))
SLEEP_SEC    = 0.6   # pause between API calls

_NIFTY200_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv"


# ── Universe ──────────────────────────────────────────────────────────────────

def load_universe():
    """Fetch current Nifty 200 constituents from NSE. Returns sorted symbol list."""
    try:
        resp = requests.get(
            _NIFTY200_URL,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = sorted(s for s in df['Symbol'].str.strip().unique() if not s.startswith('DUMMY'))
        print(f"Nifty 200 loaded from NSE: {len(symbols)} symbols")
        return symbols
    except Exception as e:
        print(f"WARNING: Could not fetch Nifty 200 from NSE ({e}). Falling back to cached list.")
        return _NIFTY200_FALLBACK


# Fallback used only when NSE website is unreachable.
# Update this list quarterly after each Nifty 200 rebalancing.
_NIFTY200_FALLBACK = sorted([
    "360ONE", "ABB", "ABCAPITAL", "ABFRL", "ADANIENT", "ADANIPORTS",
    "AMBUJACEM", "APOLLOHOSP", "ATGL", "AUROPHARMA", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "BALKRISIND",
    "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT",
    "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "CANBK",
    "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR",
    "CROMPTON", "CUMMINSIND", "DIVISLAB", "DLF", "DRREDDY", "EICHERMOT",
    "ETERNAL", "FEDERALBNK", "GAIL", "GMRAIRPORT", "GODREJCP",
    "GODREJPROP", "GRASIM", "HAVELLS", "HCLTECH", "HDFCBANK", "HEROMOTOCO",
    "HINDALCO", "ICICIBANK", "ICICIPRULI", "IDBI", "IDFCFIRSTB",
    "INDIGO", "INDIANB", "INDUSINDBK", "INDUSTOWER", "INFY", "IRB",
    "IRCTC", "ITC", "JSWSTEEL", "JUBLFOOD", "KAYNES", "KOTAKBANK",
    "KPITTECH", "LT", "LTM", "LTTS", "LUPIN", "MANKIND", "MARICO",
    "MARUTI", "MAXHEALTH", "MGL", "MOTHERSON", "MPHASIS", "MUTHOOTFIN",
    "NAUKRI", "NHPC", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC",
    "PAGEIND", "PERSISTENT", "PIIND", "PNB", "POLYCAB", "PVRINOX",
    "RAMCOCEM", "RBLBANK", "RELIANCE", "SAIL", "SBICARD", "SBILIFE",
    "SBIN", "SHREECEM", "SIEMENS", "SONACOMS", "STAR", "SUNDARMFIN",
    "SUNPHARMA", "SUPREMEIND", "SUZLON", "TATACONSUM", "TATAELXSI",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TORNTPHARM",
    "TRENT", "TRIDENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UPL",
    "VBL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZYDUSLIFE",
])


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _wilder_smooth(arr, period):
    out = np.zeros(len(arr))
    out[period] = arr[1:period + 1].sum()
    for i in range(period + 1, len(arr)):
        out[i] = out[i - 1] - out[i - 1] / period + arr[i]
    return out


def compute_adx(df, period=14):
    """Returns the last ADX value (0-100) using Wilder's smoothing."""
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    n = len(df)

    tr  = np.zeros(n)
    pdm = np.zeros(n)
    ndm = np.zeros(n)

    for i in range(1, n):
        tr[i]  = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        up, dn = h[i] - h[i-1], l[i-1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0

    atr_s = _wilder_smooth(tr,  period)
    pdm_s = _wilder_smooth(pdm, period)
    ndm_s = _wilder_smooth(ndm, period)

    with np.errstate(divide='ignore', invalid='ignore'):
        pdi = np.where(atr_s > 0, 100 * pdm_s / atr_s, 0)
        ndi = np.where(atr_s > 0, 100 * ndm_s / atr_s, 0)
        dx  = np.where((pdi + ndi) > 0, 100 * np.abs(pdi - ndi) / (pdi + ndi), 0)

    # TR/DM: prev - prev/N + curr  (running sum, scale cancels in PDI/NDI ratio)
    # DX->ADX: prev - prev/N + curr/N  (running average, must stay 0-100)
    adx   = np.zeros(n)
    start = 2 * period - 1
    if n > start:
        adx[start] = dx[period:start + 1].mean()
        for i in range(start + 1, n):
            adx[i] = adx[i - 1] - adx[i - 1] / period + dx[i] / period
    return round(float(adx[-1]), 1)


def compute_atr_pct(df, period=14):
    """Returns ATR as a percentage of the last close price."""
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    tr = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
          for i in range(1, len(df))]
    atr = float(np.mean(tr[-period:]))
    return round(atr / c[-1] * 100, 2)


# ── Validation ───────────────────────────────────────────────────────────────

def validate_tickers(dhan, instrument_df, tickers):
    """Checks each ticker resolves to a valid EQ security_id and has intraday data.

    Uses the last 2 calendar days so validation works both pre-market and during
    market hours. Returns (valid, invalid) lists.
    """
    today   = dt.date.today()
    from_dt = (today - dt.timedelta(days=2)).strftime('%Y-%m-%d') + ' 09:15:00'
    to_dt   = today.strftime('%Y-%m-%d') + ' 15:30:00'

    valid, invalid = [], []
    print(f"\nValidating {len(tickers)} tickers for intraday availability...")
    print(f"  {'Ticker':<14}  {'Status':<6}  Detail")
    print(f"  {'-'*50}")

    for ticker in tickers:
        sid = instrument_lookup(instrument_df, ticker)
        if sid is None:
            print(f"  {ticker:<14}  FAIL   security_id not found in scrip master")
            invalid.append(ticker)
            time.sleep(SLEEP_SEC)
            continue
        try:
            result  = dhan.intraday_minute_data(
                security_id=sid,
                exchange_segment='NSE_EQ',
                instrument_type='EQUITY',
                interval=5,
                from_date=from_dt,
                to_date=to_dt,
            )
            candles = len(result.get('data', {}).get('close', []))
            if candles > 0:
                print(f"  {ticker:<14}  OK     {candles} candles  security_id={sid}")
                valid.append(ticker)
            else:
                print(f"  {ticker:<14}  FAIL   0 candles returned  security_id={sid}")
                invalid.append(ticker)
        except Exception as e:
            print(f"  {ticker:<14}  FAIL   {e}")
            invalid.append(ticker)
        time.sleep(SLEEP_SEC)

    print(f"\n  {len(valid)} valid  |  {len(invalid)} removed", end="")
    print(f": {invalid}" if invalid else "")
    return valid, invalid


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv('.env', override=True)

    universe      = load_universe()
    dhan          = load_session()
    instrument_df = get_instruments()

    today = dt.date.today()
    print(f"\nTicker screener -- {today}  |  universe={len(universe)}  "
          f"filters: ADX>={ADX_MIN}, ATR%>={ATR_PCT_MIN}  top={TOP_N}\n")

    results = []
    errors  = []

    for i, ticker in enumerate(universe, 1):
        try:
            df = fetch_ohlc(dhan, instrument_df, ticker, 'day', LOOKBACK)
            if len(df) < 30:
                print(f"  [{i:3d}/{len(universe)}] {ticker:<14} SKIP  (only {len(df)} days)")
                continue
            adx     = compute_adx(df)
            atr_pct = compute_atr_pct(df)
            close   = round(float(df['close'].iloc[-1]), 1)
            results.append({'ticker': ticker, 'adx': adx, 'atr_pct': atr_pct, 'close': close})
            flag = " +" if adx >= ADX_MIN and atr_pct >= ATR_PCT_MIN else ""
            print(f"  [{i:3d}/{len(universe)}] {ticker:<14}  ADX={adx:5.1f}  ATR%={atr_pct:5.2f}%  "
                  f"close={close:>9.1f}{flag}")
        except Exception as e:
            errors.append(ticker)
            print(f"  [{i:3d}/{len(universe)}] {ticker:<14}  ERROR: {e}")
        time.sleep(SLEEP_SEC)

    if not results:
        print("\nNo results — check API connection and credentials.")
        return

    df_res   = pd.DataFrame(results)
    filtered = df_res[(df_res['adx'] >= ADX_MIN) & (df_res['atr_pct'] >= ATR_PCT_MIN)]
    top      = filtered.sort_values('adx', ascending=False).head(TOP_N).reset_index(drop=True)

    print(f"\n{'-' * 62}")
    print(f"  {'#':<4} {'Ticker':<14} {'ADX':>6}  {'ATR%':>6}  {'Close':>9}")
    print(f"{'-' * 62}")
    for rank, row in top.iterrows():
        print(f"  {rank+1:<4} {row['ticker']:<14} {row['adx']:>6.1f}  {row['atr_pct']:>6.2f}%  "
              f"{row['close']:>9.1f}")
    print(f"{'-' * 62}")
    print(f"  {len(top)} selected  |  {len(filtered)} passed filters  |  "
          f"{len(df_res)} screened  |  {len(errors)} errors")

    valid, _ = validate_tickers(dhan, instrument_df, top['ticker'].tolist())
    top = top[top['ticker'].isin(valid)].reset_index(drop=True)

    tickers_line = 'TICKERS="' + ",".join(top['ticker'].tolist()) + '"'
    print(f"\n{'-' * 62}")
    print(tickers_line)
    print(f"{'-' * 62}")
    print("\nPaste the TICKERS= line above into .env, then start the bot.")


if __name__ == '__main__':
    main()
