import numpy as np
import pandas as pd
import pytest

from src.indicators import atr, supertrend, sl_price, update_st_direction


def _ohlcv(closes, spread=2.0):
    """Build a simple OHLCV DataFrame from a close price list."""
    closes = np.array(closes, dtype=float)
    index = pd.date_range('2026-01-01 09:15', periods=len(closes), freq='5min', name='date')
    return pd.DataFrame({
        'open':   closes - spread / 2,
        'high':   closes + spread,
        'low':    closes - spread,
        'close':  closes,
        'volume': np.ones(len(closes)) * 1000,
    }, index=index)


def _with_supertrends(closes, st1_vals, st2_vals, st3_vals):
    """Build an OHLCV DataFrame with pre-computed st1/st2/st3 columns."""
    df = _ohlcv(closes)
    df['st1'] = st1_vals
    df['st2'] = st2_vals
    df['st3'] = st3_vals
    return df


# ── atr ─────────────────────────────────────────────────────────────────────

class TestAtr:
    def test_returns_series_same_length(self):
        df = _ohlcv([100] * 20)
        result = atr(df, 7)
        assert len(result) == len(df)

    def test_first_n_values_are_nan(self):
        df = _ohlcv([100] * 20)
        result = atr(df, 7)
        assert result.iloc[:7].isna().all()

    def test_non_nan_after_warmup(self):
        df = _ohlcv([100] * 20)
        result = atr(df, 7)
        assert result.iloc[7:].notna().all()

    def test_constant_price_range_gives_stable_atr(self):
        # Every candle has range = 2*spread=4, so ATR should converge to 4
        df = _ohlcv([100] * 30, spread=2.0)
        result = atr(df, 7)
        assert abs(result.iloc[-1] - 4.0) < 0.5

    def test_does_not_mutate_input(self):
        df = _ohlcv([100] * 20)
        cols_before = set(df.columns)
        atr(df, 7)
        assert set(df.columns) == cols_before


# ── supertrend ───────────────────────────────────────────────────────────────

class TestSupertrend:
    def test_returns_series_with_original_index(self):
        df = _ohlcv(list(range(100, 130)))
        result = supertrend(df, 7, 3)
        pd.testing.assert_index_equal(result.index, df.index)

    def test_initial_values_are_nan(self):
        df = _ohlcv([100] * 30)
        result = supertrend(df, 7, 3)
        assert result.iloc[:7].isna().all()

    def test_strongly_uptrending_series_produces_non_nan(self):
        closes = list(range(80, 130))  # 50 candles, steadily rising
        df = _ohlcv(closes)
        result = supertrend(df, 7, 3)
        assert result.iloc[20:].notna().any()

    def test_does_not_mutate_input(self):
        df = _ohlcv(list(range(100, 130)))
        cols_before = set(df.columns)
        supertrend(df, 7, 3)
        assert set(df.columns) == cols_before


# ── sl_price ─────────────────────────────────────────────────────────────────

class TestSlPrice:
    def _make_row(self, close, st1, st2, st3):
        return pd.DataFrame(
            {'close': [close], 'st1': [st1], 'st2': [st2], 'st3': [st3]},
            index=pd.date_range('2026-01-01', periods=1)
        )

    def test_all_st_above_close_sell_scenario(self):
        # All STs above close → bearish, SL = weighted avg of two lowest STs
        df = self._make_row(close=100, st1=110, st2=120, st3=130)
        result = sl_price(df)
        expected = round(0.6 * 110 + 0.4 * 120, 1)
        assert result == expected

    def test_all_st_below_close_buy_scenario(self):
        # All STs below close → bullish, SL = weighted avg of two highest STs
        df = self._make_row(close=200, st1=170, st2=180, st3=190)
        result = sl_price(df)
        expected = round(0.6 * 190 + 0.4 * 180, 1)
        assert result == expected

    def test_mixed_st_returns_mean(self):
        # STs straddle close → SL = mean
        df = self._make_row(close=150, st1=140, st2=155, st3=160)
        result = sl_price(df)
        assert result == round((140 + 155 + 160) / 3, 1)

    def test_returns_rounded_to_one_decimal(self):
        df = self._make_row(close=200, st1=170, st2=183, st3=191)
        result = sl_price(df)
        assert result == round(result, 1)


# ── update_st_direction ───────────────────────────────────────────────────────

class TestUpdateStDirection:
    def _make_ohlcv_2rows(self, prev_close, curr_close, prev_st, curr_st):
        """Two-row DataFrame with st1=st2=st3 set to given values."""
        idx = pd.date_range('2026-01-01', periods=2, freq='5min')
        return pd.DataFrame({
            'close': [prev_close, curr_close],
            'st1':   [prev_st,    curr_st],
            'st2':   [prev_st,    curr_st],
            'st3':   [prev_st,    curr_st],
        }, index=idx)

    def test_st_crosses_above_close_marks_red(self):
        # ST was below close, now above close → bearish crossover → red
        df = self._make_ohlcv_2rows(prev_close=100, curr_close=100,
                                     prev_st=90,    curr_st=110)
        st_dir = {'RELIANCE': ['None', 'None', 'None']}
        update_st_direction(st_dir, df, 'RELIANCE')
        assert st_dir['RELIANCE'] == ['red', 'red', 'red']

    def test_st_crosses_below_close_marks_green(self):
        # ST was above close, now below close → bullish crossover → green
        df = self._make_ohlcv_2rows(prev_close=100, curr_close=100,
                                     prev_st=110,   curr_st=90)
        st_dir = {'RELIANCE': ['None', 'None', 'None']}
        update_st_direction(st_dir, df, 'RELIANCE')
        assert st_dir['RELIANCE'] == ['green', 'green', 'green']

    def test_no_crossover_leaves_direction_unchanged(self):
        # ST stays below close both rows → no crossover
        df = self._make_ohlcv_2rows(prev_close=100, curr_close=100,
                                     prev_st=90,    curr_st=95)
        st_dir = {'RELIANCE': ['green', 'green', 'green']}
        update_st_direction(st_dir, df, 'RELIANCE')
        assert st_dir['RELIANCE'] == ['green', 'green', 'green']

    def test_mutates_in_place(self):
        df = self._make_ohlcv_2rows(100, 100, 90, 110)
        st_dir = {'RELIANCE': ['None', 'None', 'None']}
        original = st_dir['RELIANCE']
        update_st_direction(st_dir, df, 'RELIANCE')
        assert st_dir['RELIANCE'] is original  # same list object, mutated


