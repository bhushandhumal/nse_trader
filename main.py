import os
import sys
import time
import logging
import datetime as dt
from dotenv import load_dotenv

from src.session import load_session
from src.data import get_instruments
from src.strategies import three_supertrends
from src.orders import square_off_all

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trader.log'),
    ]
)

# --- environment selection ---
_VALID_ENVS = ('dev', 'uat', 'prod')
_env_arg = next((a.split('=')[1] for a in sys.argv if a.startswith('--env=')), None)
if _env_arg not in _VALID_ENVS:
    print(f"Usage: python main.py --env=dev|uat|prod [--dry-run]")
    sys.exit(1)

ENV     = _env_arg
DRY_RUN = '--dry-run' in sys.argv

load_dotenv(f'.env.{ENV}', override=True)

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


if __name__ == "__main__":
    dhan = load_session()
    logging.info(f"Session loaded. env={ENV} dry_run={DRY_RUN} tickers={TICKERS} capital={CAPITAL}")

    instrument_df = get_instruments()
    logging.info(f"Instruments loaded: {len(instrument_df)} records.")

    st_dir      = {ticker: ['None', 'None', 'None'] for ticker in TICKERS}
    starttime   = time.time()
    timeout     = _next_close()
    squared_off = False

    try:
        while time.time() <= timeout:
            now = dt.datetime.now()

            # Square off all positions at 3:15 PM, once per session
            if (not squared_off
                    and now.weekday() < 5
                    and (now.hour, now.minute) >= (SQUARE_OFF_HOUR, SQUARE_OFF_MIN)):
                logging.info("Square-off time reached. Cancelling pending orders and closing all positions.")
                square_off_all(dhan, dry_run=DRY_RUN)
                squared_off = True
                break

            if not is_market_open():
                next_open = _next_market_open()
                wait_secs = (next_open - dt.datetime.now()).total_seconds()
                logging.info(f"Market closed. Sleeping until {next_open.strftime('%a %H:%M')}.")
                time.sleep(min(wait_secs, 3600))
                continue

            try:
                three_supertrends.run(dhan, instrument_df, TICKERS, CAPITAL, st_dir, dry_run=DRY_RUN)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logging.error(f"Strategy error: {e}")

            time.sleep(INTERVAL_SECONDS - ((time.time() - starttime) % INTERVAL_SECONDS))

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt. Exiting.")
    finally:
        logging.info("Bot stopped.")
