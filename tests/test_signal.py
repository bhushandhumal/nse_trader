import pandas as pd
import numpy as np
import pytest

from src.strategies.three_supertrends import signal


def _make_ohlcv(n=10, close=100.0):
    idx = pd.date_range('2026-01-01 09:15', periods=n, freq='5min', name='date')
    return pd.DataFrame({
        'close': [close] * n,
        'st1':   [np.nan] * n,
        'st2':   [np.nan] * n,
        'st3':   [np.nan] * n,
    }, index=idx)


def _with_st(df, st_val):
    """Set all three supertrend columns to the same value on every row."""
    df = df.copy()
    df['st1'] = st_val
    df['st2'] = st_val
    df['st3'] = st_val
    return df


# ── early-exit / guard cases ──────────────────────────────────────────────────

def test_too_few_rows_returns_hold_none():
    df = _make_ohlcv(n=1)
    result = signal(df, {'T': ['None', 'None', 'None']}, 'T')
    assert result == {'action': 'hold', 'sl': None}


def test_nan_in_last_supertrend_returns_hold_none():
    df = _make_ohlcv(n=5)  # st columns are all NaN
    result = signal(df, {'T': ['None', 'None', 'None']}, 'T')
    assert result == {'action': 'hold', 'sl': None}


# ── buy signal ────────────────────────────────────────────────────────────────

def test_all_green_returns_buy():
    df = _with_st(_make_ohlcv(n=5, close=100), st_val=90)  # ST below close
    st_dir = {'T': ['green', 'green', 'green']}
    result = signal(df, st_dir, 'T')
    assert result['action'] == 'buy'
    assert result['sl'] is not None


# ── sell signal ───────────────────────────────────────────────────────────────

def test_all_red_returns_sell():
    df = _with_st(_make_ohlcv(n=5, close=100), st_val=110)  # ST above close
    st_dir = {'T': ['red', 'red', 'red']}
    result = signal(df, st_dir, 'T')
    assert result['action'] == 'sell'
    assert result['sl'] is not None


# ── hold signal ───────────────────────────────────────────────────────────────

def test_mixed_direction_returns_hold():
    df = _with_st(_make_ohlcv(n=5, close=100), st_val=90)
    st_dir = {'T': ['green', 'red', 'None']}
    result = signal(df, st_dir, 'T')
    assert result['action'] == 'hold'
    assert result['sl'] is not None  # sl is still computed even on hold


def test_uninitialised_direction_returns_hold():
    df = _with_st(_make_ohlcv(n=5, close=100), st_val=90)
    st_dir = {'T': ['None', 'None', 'None']}
    result = signal(df, st_dir, 'T')
    assert result['action'] == 'hold'


# ── sl is always a number when st values are valid ───────────────────────────

def test_sl_is_float_when_st_initialised():
    df = _with_st(_make_ohlcv(n=5, close=100), st_val=90)
    st_dir = {'T': ['None', 'None', 'None']}
    result = signal(df, st_dir, 'T')
    assert isinstance(result['sl'], float)


# ── st_dir is mutated in place ────────────────────────────────────────────────

def test_signal_mutates_st_dir():
    # ST crosses from above to below close → update_st_direction should fire green
    idx = pd.date_range('2026-01-01 09:15', periods=2, freq='5min', name='date')
    df = pd.DataFrame({
        'close': [100.0, 100.0],
        'st1':   [110.0, 90.0],   # was above, now below → green crossover
        'st2':   [110.0, 90.0],
        'st3':   [110.0, 90.0],
    }, index=idx)
    st_dir = {'T': ['None', 'None', 'None']}
    signal(df, st_dir, 'T')
    assert st_dir['T'] == ['green', 'green', 'green']
