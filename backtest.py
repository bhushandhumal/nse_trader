"""
Backtest the three-supertrend strategy on historical NSE data.

Usage:
    python backtest.py --env dev --tickers GODREJCP,DABUR --from 01-01-2025
    python backtest.py --env dev --tickers NAUKRI --from 01-06-2024 --interval 15minute --capital 5000
    python backtest.py --env dev --tickers HAVELLS --from 01-01-2025 --no-cache
"""
import logging
import argparse
from dotenv import load_dotenv

from src.data import get_instruments, fetch_ohlc_extended, save_ohlc, load_ohlc
from backtest import engine, report

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

_VALID_ENVS      = ('dev', 'uat', 'prod')
_VALID_INTERVALS = ('1minute', '5minute', '15minute', '25minute', '60minute', 'day')


def _parse_args():
    p = argparse.ArgumentParser(description='Backtest three-supertrend strategy on NSE equities.')
    p.add_argument('--env',      required=True,  choices=_VALID_ENVS,
                   help='Environment (selects .env.<env> credentials)')
    p.add_argument('--tickers',  required=True,
                   help='Comma-separated NSE symbols, e.g. GODREJCP,DABUR')
    p.add_argument('--from',     dest='from_date', required=True,
                   help='Backtest start date in dd-mm-yyyy format')
    p.add_argument('--interval', default='5minute', choices=_VALID_INTERVALS,
                   help='Candle interval (default: 5minute)')
    p.add_argument('--capital',  type=int, default=3000,
                   help='Capital per ticker in INR (default: 3000)')
    p.add_argument('--no-cache', action='store_true', dest='no_cache',
                   help='Force re-download from Dhan, ignoring cached CSV')
    return p.parse_args()


def main():
    args = _parse_args()
    load_dotenv(f'.env.{args.env}', override=True)

    tickers = [t.strip() for t in args.tickers.split(',')]
    dhan = instrument_df = None  # lazy-initialised on first cache miss

    for ticker in tickers:
        ohlc = None

        if not args.no_cache:
            ohlc = load_ohlc(ticker, args.interval)
            if ohlc is not None:
                logging.info(f"{ticker}: {len(ohlc)} bars loaded from cache.")

        if ohlc is None:
            if dhan is None:
                from src.session import load_session
                dhan = load_session()
                instrument_df = get_instruments()
                logging.info(f"Instruments loaded: {len(instrument_df)} records.")
            logging.info(f"{ticker}: fetching from Dhan API (from {args.from_date})...")
            ohlc = fetch_ohlc_extended(dhan, instrument_df, ticker, args.from_date, args.interval)
            save_ohlc(ticker, args.interval, ohlc)
            logging.info(f"{ticker}: {len(ohlc)} bars fetched and cached.")

        trades = engine.run(ohlc, ticker, args.capital)
        report.print_report(trades, ticker, args.interval, args.from_date, args.capital)


if __name__ == '__main__':
    main()
