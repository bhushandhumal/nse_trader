import time
import datetime as dt
from dotenv import load_dotenv

from src.session import load_session
from src.data import get_instruments
from src.strategies import three_supertrends

TICKERS = ["GODREJCP", "DABUR", "ICICIPRULI", "NAUKRI", "HAVELLS", "INDHOTEL"]
CAPITAL = 3000            # max capital per position (INR)
RUN_DURATION_HOURS = 6
INTERVAL_SECONDS = 300    # scan every 5 minutes


def is_market_open():
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return False
    open_time  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= now <= close_time


if __name__ == "__main__":
    load_dotenv()
    dhan = load_session()
    print("Session loaded.")

    instrument_df = get_instruments()
    print(f"Instruments loaded: {len(instrument_df)} records.")

    st_dir    = {ticker: ['None', 'None', 'None'] for ticker in TICKERS}
    starttime = time.time()
    timeout   = starttime + 60 * 60 * RUN_DURATION_HOURS

    while time.time() <= timeout:
        try:
            if is_market_open():
                three_supertrends.run(dhan, instrument_df, TICKERS, CAPITAL, st_dir)
            else:
                print("Market closed, waiting...")
            time.sleep(INTERVAL_SECONDS - ((time.time() - starttime) % INTERVAL_SECONDS))
        except KeyboardInterrupt:
            print('\nKeyboard interrupt. Exiting.')
            break
