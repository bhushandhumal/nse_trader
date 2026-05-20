import datetime as dt
import pandas as pd


def get_instruments(kite):
    """Fetches full NSE instrument dump. Call once per session and pass the result around."""
    return pd.DataFrame(kite.instruments("NSE"))


def instrument_lookup(instrument_df, symbol):
    """Returns instrument token for a symbol, or -1 if not found."""
    try:
        return instrument_df[instrument_df.tradingsymbol == symbol].instrument_token.values[0]
    except IndexError:
        return -1


def fetch_ohlc(kite, instrument_df, ticker, interval, duration):
    """Returns OHLC DataFrame for the last `duration` calendar days."""
    token = instrument_lookup(instrument_df, ticker)
    data = pd.DataFrame(
        kite.historical_data(token, dt.date.today() - dt.timedelta(duration), dt.date.today(), interval)
    )
    data.set_index("date", inplace=True)
    return data


def fetch_ohlc_extended(kite, instrument_df, ticker, inception_date, interval):
    """Returns OHLC DataFrame from inception_date to today, chunked to respect API limits.

    inception_date format: 'dd-mm-yyyy'
    """
    interval_limits = {
        'minute': 60, '3minute': 100, '5minute': 100, '10minute': 100,
        '15minute': 200, '30minute': 200, '60minute': 400, 'day': 2000,
    }
    if interval not in interval_limits:
        raise ValueError(f"Invalid interval: {interval}. Choose from {list(interval_limits)}")

    delta = interval_limits[interval]
    token = instrument_lookup(instrument_df, ticker)
    from_date = dt.datetime.strptime(inception_date + " 16:30:00", '%d-%m-%Y %H:%M:%S')
    chunks = []

    while True:
        if from_date.date() >= (dt.date.today() - dt.timedelta(delta)):
            chunks.append(pd.DataFrame(kite.historical_data(token, from_date, dt.date.today(), interval)))
            break
        to_date = from_date + dt.timedelta(delta)
        chunks.append(pd.DataFrame(kite.historical_data(token, from_date, to_date, interval)))
        from_date = to_date

    data = pd.concat(chunks, ignore_index=True)
    data.set_index("date", inplace=True)
    return data


def fetch_ltp(kite, ticker, exchange='NSE'):
    """Returns last traded price for a ticker."""
    try:
        key = f"{exchange}:{ticker}"
        return kite.ltp([key])[key]['last_price']
    except Exception as e:
        print(f"Error fetching LTP for {ticker}: {e}")
        return None
