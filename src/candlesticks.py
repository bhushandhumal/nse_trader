import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Individual pattern detectors (row-level, for use with df.apply)
# ---------------------------------------------------------------------------

def _doji_row(candle):
    total_range = candle['high'] - candle['low']
    if total_range == 0:
        return False
    tolerance = 0.05 * total_range
    upper_shadow = candle['high'] - max(candle['open'], candle['close'])
    lower_shadow = min(candle['open'], candle['close']) - candle['low']
    return upper_shadow <= tolerance and lower_shadow <= tolerance


def _marubozu_row(candle):
    body = abs(candle['close'] - candle['open'])
    total_range = candle['high'] - candle['low']
    if total_range == 0:
        return False
    return body / total_range > 0.95


# ---------------------------------------------------------------------------
# DataFrame-level pattern functions (add a boolean column)
# ---------------------------------------------------------------------------

def doji(ohlc_df):
    df = ohlc_df.copy()
    df['doji'] = df.apply(_doji_row, axis=1)
    return df


def marubozu(ohlc_df):
    df = ohlc_df.copy()
    df['marubozu'] = df.apply(_marubozu_row, axis=1)
    return df


def hammer(ohlc_df):
    """Hammer: small body near top of range, lower shadow > 2x body, tiny upper shadow."""
    df = ohlc_df.copy()
    avg_body = abs(df['close'] - df['open']).median()
    body = abs(df['close'] - df['open'])
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    total_range = df['high'] - df['low']
    df['hammer'] = (
        (lower_shadow / (0.001 + total_range) > 0.6) &
        (body < 0.5 * avg_body) &
        (upper_shadow < 0.1 * total_range)
    )
    return df


def shooting_star(ohlc_df):
    """Shooting star: small body near bottom of range, long upper shadow."""
    df = ohlc_df.copy()
    avg_body = abs(df['close'] - df['open']).median()
    body = abs(df['close'] - df['open'])
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    total_range = df['high'] - df['low']
    df['sstar'] = (
        (upper_shadow / (0.001 + total_range) > 0.6) &
        (body < 0.5 * avg_body) &
        (lower_shadow < 0.1 * total_range)
    )
    return df


# ---------------------------------------------------------------------------
# Trend and pivot support/resistance
# ---------------------------------------------------------------------------

def trend(ohlc_df, period=7):
    """Returns 'uptrend' or 'downtrend' based on SMA slope over `period` bars."""
    if len(ohlc_df) < period:
        return 'unknown'
    sma = ohlc_df['close'].rolling(window=period).mean()
    return 'uptrend' if sma.iloc[-1] > sma.iloc[-period] else 'downtrend'


def pivot_levels(ohlc_day):
    """Standard floor pivot points from the previous day's OHLC."""
    high = ohlc_day['high'].iloc[-1]
    low = ohlc_day['low'].iloc[-1]
    close = ohlc_day['close'].iloc[-1]
    p = (high + low + close) / 3
    return (
        p,
        2 * p - low,          # r1
        p + (high - low),     # r2
        high + 2 * (p - low), # r3
        2 * p - high,         # s1
        p - (high - low),     # s2
        low - 2 * (high - p), # s3
    )


def res_sup(ohlc_df, ohlc_day):
    """Returns (resistance_price, support_price) closest to the current candle's midpoint."""
    price = (
        (ohlc_df['close'].iloc[-1] + ohlc_df['open'].iloc[-1]) / 2 +
        (ohlc_df['high'].iloc[-1] + ohlc_df['low'].iloc[-1]) / 2
    ) / 2
    p, r1, r2, r3, s1, s2, s3 = pivot_levels(ohlc_day)
    level_map = {'p': p, 'r1': r1, 'r2': r2, 'r3': r3, 's1': s1, 's2': s2, 's3': s3}
    diffs = pd.Series({k: price - v for k, v in level_map.items()})
    support_key = diffs[diffs > 0].idxmin()   # closest level above price
    resist_key = diffs[diffs < 0].idxmax()    # closest level below price
    return level_map[resist_key], level_map[support_key]


# ---------------------------------------------------------------------------
# Composite pattern scanner
# ---------------------------------------------------------------------------

def candle_pattern(ohlc_df, ohlc_day):
    """Identifies the most recent candle pattern and its significance."""
    avg_candle_size = abs(ohlc_df['close'] - ohlc_df['open']).median()
    res, sup = res_sup(ohlc_df, ohlc_day)
    close = ohlc_df['close'].iloc[-1]

    signi = 'HIGH' if (
        (sup - 1.5 * avg_candle_size) < close < (sup + 1.5 * avg_candle_size) or
        (res - 1.5 * avg_candle_size) < close < (res + 1.5 * avg_candle_size)
    ) else 'low'

    pattern = ''
    is_doji = doji(ohlc_df)['doji'].iloc[-1]
    prev_close = ohlc_df['close'].iloc[-2]
    prev_open = ohlc_df['open'].iloc[-2]
    t = trend(ohlc_df.iloc[:-1], 7)

    if is_doji and close > prev_close and close > ohlc_df['open'].iloc[-1]:
        pattern += 'doji_bullish '
    if is_doji and close < prev_close and close < ohlc_df['open'].iloc[-1]:
        pattern += 'doji_bearish '

    is_maru = marubozu(ohlc_df)['marubozu'].iloc[-1]
    if is_maru:
        body_size = abs(close - ohlc_df['open'].iloc[-1])
        if body_size < 2 * avg_candle_size:
            pattern += 'marubozu_small '
        elif close > ohlc_df['open'].iloc[-1]:
            pattern += 'marubozu_bullish '
        else:
            pattern += 'marubozu_bearish '

    is_hammer = hammer(ohlc_df)['hammer'].iloc[-1]
    if t == 'uptrend' and is_hammer:
        pattern += 'hanging_man_bearish '
    if t == 'downtrend' and is_hammer:
        pattern += 'hammer_bullish '

    is_sstar = shooting_star(ohlc_df)['sstar'].iloc[-1]
    if t == 'uptrend' and is_sstar:
        pattern += 'shooting_star_bearish '

    if is_doji and t == 'uptrend' and ohlc_df['high'].iloc[-1] < prev_close and ohlc_df['low'].iloc[-1] > prev_open:
        pattern += 'harami_cross_bearish '
    if is_doji and t == 'downtrend' and ohlc_df['high'].iloc[-1] < prev_open and ohlc_df['low'].iloc[-1] > prev_close:
        pattern += 'harami_cross_bullish '

    if is_doji and t == 'uptrend' and ohlc_df['open'].iloc[-1] > ohlc_df['high'].iloc[-2] and close < ohlc_df['low'].iloc[-2]:
        pattern += 'engulfing_bearish '
    if is_doji and t == 'downtrend' and close > ohlc_df['high'].iloc[-2] and ohlc_df['open'].iloc[-1] < ohlc_df['low'].iloc[-2]:
        pattern += 'engulfing_bullish '

    return f"Significance: {signi} | Pattern: {pattern.strip() or 'none'}"
