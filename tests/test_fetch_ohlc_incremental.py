import datetime as dt
import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.data import fetch_ohlc_incremental


def _make_ohlcv(last_ts, n=10, freq='5min'):
    """Create a minimal OHLCV DataFrame with DatetimeIndex ending at last_ts."""
    index = pd.date_range(end=last_ts, periods=n, freq=freq, name='date')
    rng = np.arange(1, n + 1, dtype=float)
    return pd.DataFrame({
        'open':   rng * 100,
        'high':   rng * 105,
        'low':    rng * 95,
        'close':  rng * 102,
        'volume': rng * 1000,
    }, index=index)


def _success_result(df):
    """Wrap a DataFrame into the Dhan API success response format."""
    return {
        'status': 'success',
        'data': {
            'open':       df['open'].tolist(),
            'high':       df['high'].tolist(),
            'low':        df['low'].tolist(),
            'close':      df['close'].tolist(),
            'volume':     df['volume'].tolist(),
            'start_Time': [int(ts.timestamp()) for ts in df.index],
        }
    }


@pytest.fixture
def dhan():
    return MagicMock()


@pytest.fixture
def instrument_df():
    return MagicMock()


# --- no cache: full fetch ---

@patch('src.data.save_ohlc')
@patch('src.data.fetch_ohlc')
@patch('src.data.load_ohlc', return_value=None)
def test_no_cache_triggers_full_fetch(mock_load, mock_fetch, mock_save, dhan, instrument_df):
    today = dt.date.today()
    full_df = _make_ohlcv(pd.Timestamp(today))
    mock_fetch.return_value = full_df

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    mock_fetch.assert_called_once_with(dhan, instrument_df, 'RELIANCE', '5minute', 4)
    mock_save.assert_called_once_with('RELIANCE', '5minute', full_df)
    assert result is full_df


@patch('src.data.save_ohlc')
@patch('src.data.fetch_ohlc')
@patch('src.data.load_ohlc')
def test_stale_cache_triggers_full_fetch(mock_load, mock_fetch, mock_save, dhan, instrument_df):
    stale_ts = pd.Timestamp(dt.date.today() - dt.timedelta(days=3))
    mock_load.return_value = _make_ohlcv(stale_ts)
    full_df = _make_ohlcv(pd.Timestamp(dt.date.today()))
    mock_fetch.return_value = full_df

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    mock_fetch.assert_called_once()
    assert result is full_df


# --- fresh cache: incremental fetch ---

@patch('src.data.save_ohlc')
@patch('src.data.fetch_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_fresh_cache_skips_full_fetch(mock_load, mock_lookup, mock_fetch, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    mock_load.return_value = _make_ohlcv(last_ts)
    dhan.intraday_minute_data.return_value = {'status': 'failure', 'data': '', 'remarks': {}}

    fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    mock_fetch.assert_not_called()
    dhan.intraday_minute_data.assert_called_once()


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_new_candles_appended_to_cache(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    cached_df = _make_ohlcv(last_ts, n=10)
    mock_load.return_value = cached_df

    new_ts = last_ts + pd.Timedelta(minutes=5)
    new_df = _make_ohlcv(new_ts, n=1)
    dhan.intraday_minute_data.return_value = _success_result(new_df)

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    assert len(result) == 11
    assert result.index[-1] == new_ts


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_api_failure_returns_cached_data(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    cached_df = _make_ohlcv(last_ts)
    mock_load.return_value = cached_df
    dhan.intraday_minute_data.return_value = {'status': 'failure', 'data': '', 'remarks': {}}

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    assert len(result) == len(cached_df)


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_api_exception_returns_cached_data(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    cached_df = _make_ohlcv(last_ts)
    mock_load.return_value = cached_df
    dhan.intraday_minute_data.side_effect = Exception("network error")

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    assert len(result) == len(cached_df)


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_combined_data_trimmed_to_duration(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    # Cache has candles from 5 days ago to today
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    old_df  = _make_ohlcv(pd.Timestamp(dt.date.today() - dt.timedelta(days=5)), n=5)
    new_df  = _make_ohlcv(last_ts, n=5)
    cached_df = pd.concat([old_df, new_df])
    cached_df.index.name = 'date'
    mock_load.return_value = cached_df
    dhan.intraday_minute_data.return_value = {'status': 'failure', 'data': '', 'remarks': {}}

    result = fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    cutoff = pd.Timestamp(dt.date.today() - dt.timedelta(days=4))
    assert result.index.min() >= cutoff


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value=None)
@patch('src.data.load_ohlc')
def test_unknown_ticker_raises(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    mock_load.return_value = _make_ohlcv(last_ts)

    with pytest.raises(ValueError, match="Instrument not found"):
        fetch_ohlc_incremental(dhan, instrument_df, 'UNKNOWN', '5minute', 4)


@patch('src.data.save_ohlc')
@patch('src.data.instrument_lookup', return_value='12345')
@patch('src.data.load_ohlc')
def test_incremental_from_date_is_after_last_cached_candle(mock_load, mock_lookup, mock_save, dhan, instrument_df):
    last_ts = pd.Timestamp(dt.date.today()) + pd.Timedelta(hours=10)
    mock_load.return_value = _make_ohlcv(last_ts)
    dhan.intraday_minute_data.return_value = {'status': 'failure', 'data': '', 'remarks': {}}

    fetch_ohlc_incremental(dhan, instrument_df, 'RELIANCE', '5minute', 4)

    call_kwargs = dhan.intraday_minute_data.call_args.kwargs
    expected_from = (last_ts + pd.Timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    assert call_kwargs['from_date'] == expected_from
