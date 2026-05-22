import io
import logging
import datetime as dt
from pathlib import Path
import pandas as pd
import requests

_CACHE_DIR = Path('data/cache')

# TODO (multi-broker): this module is Dhan-specific. Future refactor: move behind
# a BaseBroker.get_instruments() / BaseBroker.fetch_ohlc() interface.

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# Maps interval strings to Dhan's minute values (1, 5, 15, 25, 60)
_INTERVAL_MAP = {
    '1minute': 1,
    '5minute': 5,
    '15minute': 15,
    '25minute': 25,
    '60minute': 60,
}


def get_instruments():
    """Downloads Dhan scrip master CSV. Call once per session and pass the result around."""
    resp = requests.get(SCRIP_MASTER_URL, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), low_memory=False)


def instrument_lookup(instrument_df, symbol):
    """Returns Dhan security_id (str) for an NSE equity symbol, or None if not found."""
    try:
        mask = (
            (instrument_df['SEM_TRADING_SYMBOL'] == symbol) &
            (instrument_df['SEM_EXM_EXCH_ID'] == 'NSE') &
            (instrument_df['SEM_INSTRUMENT_NAME'] == 'EQUITY')
        )
        return str(instrument_df[mask]['SEM_SMST_SECURITY_ID'].values[0])
    except IndexError:
        return None


def _response_to_df(result):
    """Normalises a Dhan historical/intraday response to a date-indexed OHLCV DataFrame."""
    data = result.get('data', result)
    df = pd.DataFrame({
        'open':   data['open'],
        'high':   data['high'],
        'low':    data['low'],
        'close':  data['close'],
        'volume': data['volume'],
    }, index=pd.to_datetime(data['timestamp'], unit='s'))
    df.index.name = 'date'
    return df


def fetch_ohlc(dhan, instrument_df, ticker, interval, duration):
    """Returns OHLC DataFrame for the last `duration` calendar days.

    interval: 'day' | '1minute' | '5minute' | '15minute' | '25minute' | '60minute'
    """
    security_id = instrument_lookup(instrument_df, ticker)
    if security_id is None:
        raise ValueError(f"Instrument not found: {ticker}")

    to_dt   = dt.date.today()
    from_dt = to_dt - dt.timedelta(duration)

    if interval == 'day':
        result = dhan.historical_daily_data(
            security_id=security_id,
            exchange_segment='NSE_EQ',
            instrument_type='EQUITY',
            from_date=from_dt.strftime('%Y-%m-%d'),
            to_date=to_dt.strftime('%Y-%m-%d'),
        )
    else:
        if interval not in _INTERVAL_MAP:
            raise ValueError(f"Invalid interval '{interval}'. Choose from: day, {', '.join(_INTERVAL_MAP)}")
        result = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment='NSE_EQ',
            instrument_type='EQUITY',
            interval=_INTERVAL_MAP[interval],
            from_date=from_dt.strftime('%Y-%m-%d') + ' 09:15:00',
            to_date=to_dt.strftime('%Y-%m-%d') + ' 15:30:00',
        )

    return _response_to_df(result)


def fetch_ohlc_extended(dhan, instrument_df, ticker, inception_date, interval):
    """Returns OHLC DataFrame from inception_date to today, chunked within Dhan's 90-day limit.

    inception_date format: 'dd-mm-yyyy'
    interval: 'day' | '1minute' | '5minute' | '15minute' | '25minute' | '60minute'
    """
    security_id = instrument_lookup(instrument_df, ticker)
    if security_id is None:
        raise ValueError(f"Instrument not found: {ticker}")

    from_dt = dt.datetime.strptime(inception_date, '%d-%m-%Y').date()
    to_dt   = dt.date.today()
    chunk_days = 90 if interval != 'day' else 365
    chunks = []

    while from_dt < to_dt:
        chunk_end = min(from_dt + dt.timedelta(chunk_days), to_dt)
        if interval == 'day':
            result = dhan.historical_daily_data(
                security_id=security_id,
                exchange_segment='NSE_EQ',
                instrument_type='EQUITY',
                from_date=from_dt.strftime('%Y-%m-%d'),
                to_date=chunk_end.strftime('%Y-%m-%d'),
            )
        else:
            result = dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment='NSE_EQ',
                instrument_type='EQUITY',
                interval=_INTERVAL_MAP[interval],
                from_date=from_dt.strftime('%Y-%m-%d') + ' 09:15:00',
                to_date=chunk_end.strftime('%Y-%m-%d') + ' 15:30:00',
            )
        chunks.append(_response_to_df(result))
        from_dt = chunk_end + dt.timedelta(1)

    return pd.concat(chunks)


def save_ohlc(ticker, interval, df):
    """Saves an OHLCV DataFrame to the local cache as a CSV."""
    path = _CACHE_DIR / f'{ticker}_{interval}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)


def load_ohlc(ticker, interval):
    """Loads a cached OHLCV DataFrame, or returns None if not cached."""
    path = _CACHE_DIR / f'{ticker}_{interval}.csv'
    if not path.exists():
        return None
    return pd.read_csv(path, index_col='date', parse_dates=True)


def fetch_ltp(dhan, instrument_df, ticker):
    """Returns last traded price for an NSE equity ticker."""
    security_id = instrument_lookup(instrument_df, ticker)
    if security_id is None:
        return None
    try:
        result = dhan.ohlc_data(securities={'NSE_EQ': [int(security_id)]})
        if result.get('status') != 'success':
            return None
        # Fix 5: Dhan may key the response by int or str — try both
        nse_data = result['data']['NSE_EQ']
        ltp_entry = nse_data.get(security_id) or nse_data.get(int(security_id))
        if ltp_entry is None:
            return None
        return ltp_entry['last_price']
    except Exception as e:
        logging.error(f"Error fetching LTP for {ticker}: {e}")
        return None
