import os
import sys
import time
import logging
import datetime as dt
from dotenv import load_dotenv

from src.session import load_session
from src.data import get_instruments, fetch_ohlc, save_ohlc
from src.strategies import three_supertrends
from src.orders import square_off_all, verify_order_placement
from src.reporter import print_eod_report
from src.paper_broker import PaperBroker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'trader_{dt.date.today()}.log'),
    ]
)

DRY_RUN = '--dry-run' in sys.argv

load_dotenv('.env', override=True)

# --- config (env file can override these defaults) ---
CAPITAL          = int(os.getenv('CAPITAL', 3000))
TICKERS          = os.getenv('TICKERS', 'GODREJCP,DABUR,ICICIPRULI,NAUKRI,HAVELLS,INDHOTEL').split(',')
INTERVAL_SECONDS = 300
SQUARE_OFF_HOUR  = 15
SQUARE_OFF_MIN   = 15  # square off at 3:15 PM, before Dhan's 3:20 PM auto-square-off


def is_market_open():
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return False
    open_time  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= now <= close_time


def _is_square_off_time(now=None):
    """True on a weekday at/after the square-off time (3:15 PM)."""
    now = now or dt.datetime.now()
    return now.weekday() < 5 and (now.hour, now.minute) >= (SQUARE_OFF_HOUR, SQUARE_OFF_MIN)


def _next_market_open():
    now    = dt.datetime.now()
    target = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now >= target or now.weekday() >= 5:
        target += dt.timedelta(days=1)
        while target.weekday() >= 5:
            target += dt.timedelta(days=1)
    return target


def _next_close():
    """Returns timestamp of 15:30 for the current or next trading day."""
    now   = dt.datetime.now()
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now >= close or now.weekday() >= 5:
        close += dt.timedelta(days=1)
        while close.weekday() >= 5:
            close += dt.timedelta(days=1)
        close = close.replace(hour=15, minute=30, second=0, microsecond=0)
    return close.timestamp()


def _build_strategies(tickers, capital):
    """Returns the strategy registry. Add new strategies here."""
    return [
        {
            'name':    'Three Supertrends',
            'module':  three_supertrends,
            'tickers': tickers,
            'capital': capital,
            'state': {
                'st_dir':       {t: ['None', 'None', 'None'] for t in tickers},
                'prev_signals': {t: 'hold' for t in tickers},
                'trades':       [],
            },
        },
        # To add a second strategy, append another dict here:
        # {
        #     'name':    'SMA Crossover',
        #     'module':  sma_crossover,
        #     'tickers': ['INFY', 'TCS'],
        #     'capital': capital // 2,
        #     'state':   {'prev_signals': {}, 'trades': []},
        # },
    ]


if __name__ == "__main__":
    dhan = load_session()
    logging.info(f"Session loaded. dry_run={DRY_RUN} tickers={TICKERS} capital={CAPITAL}")

    instrument_df = get_instruments()
    logging.info(f"Instruments loaded: {len(instrument_df)} records.")

    # In dry-run, route orders through an in-memory paper broker instead of the
    # log-only shortcut. The real order path (place_sl_order / modify_sl_order /
    # square_off_all) then runs against simulated fills, so the SL actually trails
    # and exits/P&L are simulated — a faithful proxy for live. The wrapper delegates
    # all market-data calls to the real client, so OHLC/quotes are still real.
    if DRY_RUN:
        dhan = PaperBroker(dhan, instrument_df)
        logging.info("DRY RUN: orders routed through in-memory PaperBroker "
                     "(simulated fills, real SL trailing + P&L).")

    # Preflight: confirm the broker will accept live orders before we start trading.
    # Skipped in dry-run (no real orders are placed there anyway).
    if not DRY_RUN:
        if not verify_order_placement(dhan, instrument_df, TICKERS):
            logging.error("Order-placement preflight FAILED — aborting before the trading loop. "
                          "Likely Dhan IP whitelist / stale token. Fix: whitelist this machine's "
                          "public IPv4 on Dhan and regenerate the token (delete .token_cache), "
                          "then restart.")
            sys.exit(1)

    strategies = _build_strategies(TICKERS, CAPITAL)

    all_tickers = list({t for s in strategies for t in s['tickers']})
    logging.info("Pre-loading OHLC cache for all tickers...")
    for ticker in all_tickers:
        try:
            df = fetch_ohlc(dhan, instrument_df, ticker, '5minute', 4)
            save_ohlc(ticker, '5minute', df)
            logging.info(f"  Cached {ticker}: {len(df)} candles")
        except Exception as e:
            logging.warning(f"  Failed to cache {ticker}: {e}")
        time.sleep(1)
    logging.info("Pre-load complete.")

    starttime   = time.time()
    timeout     = _next_close()
    squared_off = False

    try:
        while time.time() <= timeout:
            now = dt.datetime.now()

            # Square off all positions at 3:15 PM, once per session
            if not squared_off and _is_square_off_time(now):
                logging.info("Square-off time reached. Cancelling pending orders and closing all positions.")
                # dry_run=False even in a dry run: the PaperBroker (swapped in above)
                # provides the simulation, so the real square-off path must execute.
                square_off_all(dhan, dry_run=False)
                squared_off = True
                for s in strategies:
                    print_eod_report(s['name'], s['state'], dhan)
                break

            if not is_market_open():
                next_open = _next_market_open()
                wait_secs = (next_open - dt.datetime.now()).total_seconds()
                logging.info(f"Market closed. Sleeping until {next_open.strftime('%a %H:%M')}.")
                time.sleep(min(wait_secs, 3600))
                continue

            for s in strategies:
                try:
                    # dry_run=False: the PaperBroker handles dry-run simulation, so the
                    # strategy runs its real order path (entry + trailing SL) against it.
                    s['module'].run(dhan, instrument_df, s['tickers'], s['capital'], s['state'], dry_run=False)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logging.error(f"Strategy '{s['name']}' error: {e}")

            # Interruptible wait until the next cycle: poll every 10s and break out
            # the moment square-off time arrives, so we fire it within seconds of
            # 3:15 PM and beat the broker's auto-square-off — instead of being up to
            # one full interval (5 min) late, as happened before this guard.
            next_cycle = time.time() + (INTERVAL_SECONDS - ((time.time() - starttime) % INTERVAL_SECONDS))
            while time.time() < next_cycle and not _is_square_off_time():
                time.sleep(min(10, next_cycle - time.time()))

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt. Exiting.")
        for s in strategies:
            print_eod_report(s['name'], s['state'], dhan)
    finally:
        logging.info("Bot stopped.")
