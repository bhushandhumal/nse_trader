import pandas as pd
import numpy as np
import pytest

from src.candlesticks import (
    _doji_row, _marubozu_row,
    doji, marubozu, hammer, shooting_star,
    trend, pivot_levels, res_sup,
)


def _candle(open_, high, low, close):
    return pd.Series({'open': open_, 'high': high, 'low': low, 'close': close})


def _df(rows, n=20):
    """Build a DataFrame from a list of (o,h,l,c) tuples, padding with neutral candles.

    Neutral candles have body=4 so avg_body (median) is non-zero for hammer/shooting_star tests.
    """
    neutral = [(98, 102, 98, 102)] * max(0, n - len(rows))
    all_rows = neutral + list(rows)
    idx = pd.date_range('2026-01-01', periods=len(all_rows), freq='5min')
    return pd.DataFrame(all_rows, columns=['open', 'high', 'low', 'close'], index=idx)


# ── _doji_row ─────────────────────────────────────────────────────────────────

class TestDojiRow:
    def test_doji_tiny_body(self):
        # open ≈ close, long upper and lower shadows
        assert _doji_row(_candle(100, 110, 90, 100.1)) == True

    def test_not_doji_large_body(self):
        assert _doji_row(_candle(100, 110, 90, 108)) == False

    def test_zero_range_returns_false(self):
        assert _doji_row(_candle(100, 100, 100, 100)) == False


# ── _marubozu_row ─────────────────────────────────────────────────────────────

class TestMarubozuRow:
    def test_marubozu_body_fills_range(self):
        # body = 10, range = 10 → ratio = 1.0 > 0.95
        assert _marubozu_row(_candle(100, 110, 100, 110)) == True

    def test_not_marubozu_small_body(self):
        # body = 1, range = 20 → ratio = 0.05
        assert _marubozu_row(_candle(100, 110, 90, 101)) == False

    def test_zero_range_returns_false(self):
        assert _marubozu_row(_candle(100, 100, 100, 100)) == False


# ── doji / marubozu DataFrame functions ──────────────────────────────────────

class TestDojiDf:
    def test_adds_doji_column(self):
        df = _df([(100, 110, 90, 100.1)])
        result = doji(df)
        assert 'doji' in result.columns

    def test_does_not_mutate_input(self):
        df = _df([(100, 110, 90, 100.1)])
        doji(df)
        assert 'doji' not in df.columns

    def test_last_row_detected_as_doji(self):
        df = _df([(100, 110, 90, 100.1)])
        assert doji(df)['doji'].iloc[-1] is True or doji(df)['doji'].iloc[-1] == True


class TestMarubozuDf:
    def test_adds_marubozu_column(self):
        df = _df([(100, 110, 100, 110)])
        assert 'marubozu' in marubozu(df).columns

    def test_last_row_detected_as_marubozu(self):
        df = _df([(100, 110, 100, 110)])
        assert marubozu(df)['marubozu'].iloc[-1] == True


# ── hammer ────────────────────────────────────────────────────────────────────

class TestHammer:
    def test_adds_hammer_column(self):
        df = _df([])
        assert 'hammer' in hammer(df).columns

    def test_hammer_candle_detected(self):
        # Small body near top, long lower shadow
        # open=109, close=110, high=110, low=100 → lower shadow=9, body=1, upper shadow=0
        rows = [(109, 110, 100, 110)]
        df = _df(rows)
        assert hammer(df)['hammer'].iloc[-1] == True

    def test_non_hammer_rejected(self):
        # Normal candle with balanced shadows
        rows = [(100, 110, 90, 105)]
        df = _df(rows)
        assert hammer(df)['hammer'].iloc[-1] == False


# ── shooting_star ─────────────────────────────────────────────────────────────

class TestShootingStar:
    def test_adds_sstar_column(self):
        df = _df([])
        assert 'sstar' in shooting_star(df).columns

    def test_shooting_star_detected(self):
        # Small body near bottom, long upper shadow
        # open=100, close=101, high=110, low=100 → upper shadow=9, body=1, lower shadow=0
        rows = [(100, 110, 100, 101)]
        df = _df(rows)
        assert shooting_star(df)['sstar'].iloc[-1] == True

    def test_non_shooting_star_rejected(self):
        rows = [(100, 110, 90, 105)]
        df = _df(rows)
        assert shooting_star(df)['sstar'].iloc[-1] == False


# ── trend ─────────────────────────────────────────────────────────────────────

class TestTrend:
    def test_uptrend(self):
        closes = list(range(100, 115))
        idx = pd.date_range('2026-01-01', periods=len(closes), freq='5min')
        df = pd.DataFrame({'close': closes}, index=idx)
        assert trend(df, 7) == 'uptrend'

    def test_downtrend(self):
        closes = list(range(115, 100, -1))
        idx = pd.date_range('2026-01-01', periods=len(closes), freq='5min')
        df = pd.DataFrame({'close': closes}, index=idx)
        assert trend(df, 7) == 'downtrend'

    def test_too_few_candles_returns_unknown(self):
        closes = [100, 101, 102]
        idx = pd.date_range('2026-01-01', periods=3, freq='5min')
        df = pd.DataFrame({'close': closes}, index=idx)
        assert trend(df, 7) == 'unknown'


# ── pivot_levels ──────────────────────────────────────────────────────────────

class TestPivotLevels:
    def test_returns_7_levels(self):
        idx = pd.date_range('2026-01-01', periods=1)
        day = pd.DataFrame({'high': [120], 'low': [80], 'close': [100]}, index=idx)
        result = pivot_levels(day)
        assert len(result) == 7

    def test_pivot_formula(self):
        idx = pd.date_range('2026-01-01', periods=1)
        day = pd.DataFrame({'high': [120], 'low': [80], 'close': [100]}, index=idx)
        p, r1, r2, r3, s1, s2, s3 = pivot_levels(day)
        expected_p = (120 + 80 + 100) / 3
        assert abs(p - expected_p) < 1e-9

    def test_r1_above_pivot(self):
        idx = pd.date_range('2026-01-01', periods=1)
        day = pd.DataFrame({'high': [120], 'low': [80], 'close': [100]}, index=idx)
        p, r1, *_ = pivot_levels(day)
        assert r1 > p

    def test_s1_below_pivot(self):
        idx = pd.date_range('2026-01-01', periods=1)
        day = pd.DataFrame({'high': [120], 'low': [80], 'close': [100]}, index=idx)
        p, _, _, _, s1, *_ = pivot_levels(day)
        assert s1 < p
