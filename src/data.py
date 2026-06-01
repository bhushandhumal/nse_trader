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
            (instrument_df['SEM_INSTRUMENT_NAME'] == 'EQUITY') &
            (instrument_df['SEM_SERIES'] == 'EQ')
        )
        return str(instrument_df[mask]['SEM_SMST_SECURITY_ID'].values[0])
    except IndexError:
        return None


def get_tick_size(instrument_df, symbol):
    """Returns the NSE-equity tick size in rupees for a symbol (default 0.05).

    Dhan's scrip master stores SEM_TICK_SIZE in paise (1.0 -> Rs 0.01,
    10.0 -> Rs 0.10, 50.0 -> Rs 0.50). Order prices must be a multiple of this
    or the exchange rejects them (EXCH:16283).
    """
    try:
        mask = (
            (instrument_df['SEM_TRADING_SYMBOL'] == symbol) &
            (instrument_df['SEM_EXM_EXCH_ID'] == 'NSE') &
            (instrument_df['SEM_INSTRUMENT_NAME'] == 'EQUITY') &
            (instrument_df['SEM_SERIES'] == 'EQ')
        )
        tick = round(float(instrument_df[mask]['SEM_TICK_SIZE'].values[0]) / 100.0, 2)
        return tick if tick > 0 else 0.05
    except (IndexError, ValueError, KeyError, TypeError):
        return 0.05


def _response_to_df(result):
    """Normalises a Dhan historical/intraday response to a date-indexed OHLCV DataFrame."""
    if result.get('status') == 'failure':
        raise ValueError(f"Dhan API error: {result.get('remarks', result)}")
    data = result.get('data', result)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected response format: {result}")
    ts_key = 'start_Time' if 'start_Time' in data else 'timestamp'
    df = pd.DataFrame({
        'open':   data['open'],
        'high':   data['high'],
        'low':    data['low'],
        'close':  data['close'],
        'volume': data['volume'],
    }, index=pd.to_datetime(data[ts_key], unit='s'))
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


def fetch_ohlc_incremental(dhan, instrument_df, ticker, interval, duration):
    """Returns OHLC DataFrame using cache for history and only fetching new candles each call.

    Falls back to a full fetch if no cache exists or cache is from a previous day.
    """
    cached = load_ohlc(ticker, interval)
    today = dt.date.today()

    if cached is not None and not cached.empty and cached.index[-1].date() >= today - dt.timedelta(1):
        security_id = instrument_lookup(instrument_df, ticker)
        if security_id is None:
            raise ValueError(f"Instrument not found: {ticker}")

        interval_mins = _INTERVAL_MAP.get(interval, 5)
        last_ts = cached.index[-1]
        from_dt = (last_ts + pd.Timedelta(minutes=interval_mins)).strftime('%Y-%m-%d %H:%M:%S')
        to_dt   = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            result = dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment='NSE_EQ',
                instrument_type='EQUITY',
                interval=interval_mins,
                from_date=from_dt,
                to_date=to_dt,
            )
            if result.get('status') == 'success':
                new_df = _response_to_df(result)
                combined = pd.concat([cached, new_df])
                combined = combined[~combined.index.duplicated(keep='last')]
            else:
                combined = cached
        except Exception:
            combined = cached

        cutoff = pd.Timestamp(today - dt.timedelta(days=duration))
        combined = combined[combined.index >= cutoff]
        save_ohlc(ticker, interval, combined)
        return combined

    df = fetch_ohlc(dhan, instrument_df, ticker, interval, duration)
    save_ohlc(ticker, interval, df)
    return df


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
        # Fix 6: SDK nests the payload as data -> data -> NSE_EQ -> "<security_id>"
        payload  = result.get('data', {})
        nse_data = payload.get('data', payload).get('NSE_EQ', {})
        # Fix 5: Dhan may key the response by int or str — try both
        ltp_entry = nse_data.get(security_id) or nse_data.get(int(security_id))
        if ltp_entry is None:
            return None
        return ltp_entry['last_price']
    except Exception as e:
        logging.error(f"Error fetching LTP for {ticker}: {e}")
        return None
