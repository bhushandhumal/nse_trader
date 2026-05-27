"""
Tests for three_supertrends.run() — orchestration logic only.
Signal computation is tested separately in test_signal.py.
"""
import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.strategies.three_supertrends import run


TICKER = 'BHEL'
TICKERS = [TICKER]

_PATCH_FETCH  = 'src.strategies.three_supertrends.fetch_ohlc_incremental'
_PATCH_SIGNAL = 'src.strategies.three_supertrends.signal'
_PATCH_LOOKUP = 'src.strategies.three_supertrends.instrument_lookup'
_PATCH_PLACE  = 'src.strategies.three_supertrends.place_sl_order'


@pytest.fixture
def dhan():
    m = MagicMock()
    m.get_positions.return_value = {'data': []}
    m.get_order_list.return_value = {'data': []}
    return m


@pytest.fixture
def instrument_df():
    return MagicMock()


@pytest.fixture
def fresh_state():
    return {
        'st_dir':       {TICKER: ['None', 'None', 'None']},
        'prev_signals': {TICKER: 'hold'},
        'trades':       [],
    }


def _fake_ohlc(close=500.0, n=20):
    idx = pd.date_range('2026-01-01 09:15', periods=n, freq='5min', name='date')
    return pd.DataFrame({'open': close, 'high': close, 'low': close,
                         'close': close, 'volume': 1000}, index=idx)


# ── trade recording ───────────────────────────────────────────────────────────

class TestTradeRecording:
    def test_buy_signal_appends_trade_to_state(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE,  return_value='ORD1'):
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        assert len(fresh_state['trades']) == 1
        trade = fresh_state['trades'][0]
        assert trade['ticker']   == TICKER
        assert trade['action']   == 'buy'
        assert trade['sl_price'] == 490.0
        assert trade['order_id'] == 'ORD1'

    def test_sell_signal_appends_trade_to_state(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'sell', 'sl': 510.0}), \
             patch(_PATCH_PLACE,  return_value='ORD2'):
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        assert len(fresh_state['trades']) == 1
        assert fresh_state['trades'][0]['action'] == 'sell'

    def test_hold_signal_does_not_append_trade(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'hold', 'sl': 490.0}), \
             patch(_PATCH_PLACE):
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        assert fresh_state['trades'] == []

    def test_dry_run_records_trade_with_none_order_id(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE,  return_value=None):
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state, dry_run=True)

        assert len(fresh_state['trades']) == 1
        assert fresh_state['trades'][0]['order_id'] is None

    def test_trade_record_contains_qty(self, dhan, instrument_df, fresh_state):
        close = 500.0
        capital = 50_000
        expected_qty = int(capital / close)  # 100
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc(close=close)), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE,  return_value='ORD1'):
            run(dhan, instrument_df, TICKERS, capital, fresh_state)

        assert fresh_state['trades'][0]['qty'] == expected_qty


# ── duplicate-entry prevention ────────────────────────────────────────────────

class TestDuplicatePrevention:
    def test_no_entry_when_signal_same_as_prev(self, dhan, instrument_df):
        state = {
            'st_dir':       {TICKER: ['green', 'green', 'green']},
            'prev_signals': {TICKER: 'buy'},   # same as incoming signal
            'trades':       [],
        }
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 100_000, state)

        mock_place.assert_not_called()
        assert state['trades'] == []

    def test_no_entry_when_position_already_held(self, dhan, instrument_df, fresh_state):
        dhan.get_positions.return_value = {'data': [
            {'tradingSymbol': TICKER, 'netQty': 50},
        ]}
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        mock_place.assert_not_called()
        assert fresh_state['trades'] == []

    def test_prev_signals_updated_after_cycle(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE,  return_value='ORD1'):
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        assert fresh_state['prev_signals'][TICKER] == 'buy'


# ── resilience ────────────────────────────────────────────────────────────────

class TestResilience:
    def test_skips_ticker_when_instrument_not_found(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value=None), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        mock_place.assert_not_called()
        assert fresh_state['trades'] == []

    def test_skips_ticker_when_capital_too_low(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc(close=100_000.0)), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 99_000.0}), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 500, fresh_state)  # capital < price

        mock_place.assert_not_called()
        assert fresh_state['trades'] == []

    def test_skips_ticker_when_sl_is_none(self, dhan, instrument_df, fresh_state):
        with patch(_PATCH_LOOKUP, return_value='SEC1'), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': None}), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        mock_place.assert_not_called()
        assert fresh_state['trades'] == []

    def test_position_fetch_failure_skips_cycle(self, dhan, instrument_df, fresh_state, caplog):
        import logging
        dhan.get_positions.side_effect = Exception("network error")
        with caplog.at_level(logging.ERROR), \
             patch(_PATCH_PLACE) as mock_place:
            run(dhan, instrument_df, TICKERS, 100_000, fresh_state)

        mock_place.assert_not_called()
        assert 'Failed to fetch positions' in caplog.text

    def test_per_ticker_exception_does_not_abort_others(self, dhan, instrument_df):
        tickers = ['BHEL', 'SBIN']
        state = {
            'st_dir':       {t: ['None', 'None', 'None'] for t in tickers},
            'prev_signals': {t: 'hold' for t in tickers},
            'trades':       [],
        }
        def lookup_side_effect(df, ticker):
            if ticker == 'BHEL':
                raise RuntimeError("simulated error")
            return 'SEC2'

        with patch(_PATCH_LOOKUP, side_effect=lookup_side_effect), \
             patch(_PATCH_FETCH,  return_value=_fake_ohlc()), \
             patch(_PATCH_SIGNAL, return_value={'action': 'buy', 'sl': 490.0}), \
             patch(_PATCH_PLACE,  return_value='ORD1'):
            run(dhan, instrument_df, tickers, 100_000, state)

        # SBIN trade should still be recorded despite BHEL failing
        assert any(t['ticker'] == 'SBIN' for t in state['trades'])
