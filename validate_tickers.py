"""
Validates all TICKERS in .env for intraday tradability on Dhan.

Checks:
  1. Ticker resolves to an EQ-series security_id in Dhan's scrip master
  2. A minimal 5-minute intraday fetch returns >0 candles (last 2 days)

Usage:
    python validate_tickers.py          # report only
    python validate_tickers.py --fix    # remove invalid tickers from .env
"""

import sys
import time
import datetime as dt
from dotenv import load_dotenv, set_key
import os

load_dotenv('.env', override=True)

from src.session import load_session
from src.data import get_instruments, instrument_lookup

SLEEP_SEC = 0.6
ENV_FILE  = '.env'


def validate(dhan, instrument_df, tickers):
    today   = dt.date.today()
    from_dt = (today - dt.timedelta(days=2)).strftime('%Y-%m-%d') + ' 09:15:00'
    to_dt   = today.strftime('%Y-%m-%d') + ' 15:30:00'

    valid, invalid = [], []
    width = max(len(t) for t in tickers)

    print(f"\n{'Ticker':<{width}}  {'Status'}  Detail")
    print('-' * 60)

    for ticker in tickers:
        sid = instrument_lookup(instrument_df, ticker)
        if sid is None:
            print(f"{ticker:<{width}}  FAIL    security_id not found (check symbol spelling)")
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
                print(f"{ticker:<{width}}  OK      {candles} candles  (id={sid})")
                valid.append(ticker)
            else:
                print(f"{ticker:<{width}}  FAIL    0 candles returned  (id={sid})")
                invalid.append(ticker)
        except Exception as e:
            print(f"{ticker:<{width}}  ERROR   {e}")
            invalid.append(ticker)
        time.sleep(SLEEP_SEC)

    return valid, invalid


def main():
    fix_mode = '--fix' in sys.argv

    raw = os.getenv('TICKERS', '')
    if not raw:
        print("No TICKERS found in .env — nothing to validate.")
        return

    tickers = [t.strip() for t in raw.strip('"').split(',') if t.strip()]
    print(f"Loaded {len(tickers)} tickers from .env")
    if fix_mode:
        print("Mode: --fix  (invalid tickers will be removed from .env)")
    else:
        print("Mode: report only  (pass --fix to auto-remove invalid tickers)")

    dhan          = load_session()
    instrument_df = get_instruments()

    valid, invalid = validate(dhan, instrument_df, tickers)

    print(f"\n{'='*60}")
    print(f"  Total : {len(tickers)}")
    print(f"  Valid : {len(valid)}")
    print(f"  Invalid ({len(invalid)}): {invalid if invalid else 'none'}")
    print(f"{'='*60}")

    if fix_mode and invalid:
        new_line = ','.join(valid)
        set_key(ENV_FILE, 'TICKERS', new_line)
        print(f"\n.env updated — {len(invalid)} ticker(s) removed: {invalid}")
    elif invalid:
        print("\nRe-run with --fix to remove invalid tickers from .env automatically.")


if __name__ == '__main__':
    main()
