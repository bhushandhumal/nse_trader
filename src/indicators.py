import numpy as np
import pandas as pd


def atr(df, n):
    """Average True Range over n periods (EWM)."""
    d = df.copy()
    d['H-L'] = abs(d['high'] - d['low'])
    d['H-PC'] = abs(d['high'] - d['close'].shift(1))
    d['L-PC'] = abs(d['low'] - d['close'].shift(1))
    d['TR'] = d[['H-L', 'H-PC', 'L-PC']].max(axis=1, skipna=False)
    return d['TR'].ewm(com=n, min_periods=n).mean()


def supertrend(df, n, m):
    """Supertrend indicator. n = ATR period (typically 7), m = multiplier (2 or 3)."""
    d = df.copy()
    d['ATR'] = atr(d, n)
    d['B-U'] = ((d['high'] + d['low']) / 2) + m * d['ATR']
    d['B-L'] = ((d['high'] + d['low']) / 2) - m * d['ATR']
    d['U-B'] = d['B-U']
    d['L-B'] = d['B-L']
    idx = d.index

    for i in range(n, len(d)):
        d.loc[idx[i], 'U-B'] = min(d['B-U'][i], d['U-B'][i - 1]) if d['close'][i - 1] <= d['U-B'][i - 1] else d['B-U'][i]

    for i in range(n, len(d)):
        d.loc[idx[i], 'L-B'] = max(d['B-L'][i], d['L-B'][i - 1]) if d['close'][i - 1] >= d['L-B'][i - 1] else d['B-L'][i]

    d['Strend'] = np.nan
    start = n
    for test in range(n, len(d)):
        if d['close'][test - 1] <= d['U-B'][test - 1] and d['close'][test] > d['U-B'][test]:
            d.loc[idx[test], 'Strend'] = d['L-B'][test]
            start = test
            break
        if d['close'][test - 1] >= d['L-B'][test - 1] and d['close'][test] < d['L-B'][test]:
            d.loc[idx[test], 'Strend'] = d['U-B'][test]
            start = test
            break

    for i in range(start + 1, len(d)):
        prev = d['Strend'][i - 1]
        if prev == d['U-B'][i - 1]:
            d.loc[idx[i], 'Strend'] = d['U-B'][i] if d['close'][i] <= d['U-B'][i] else d['L-B'][i]
        elif prev == d['L-B'][i - 1]:
            d.loc[idx[i], 'Strend'] = d['L-B'][i] if d['close'][i] >= d['L-B'][i] else d['U-B'][i]

    return d['Strend']


def sl_price(ohlc):
    """Stop-loss price derived from the three supertrend values on the last candle."""
    st = ohlc.iloc[-1][['st1', 'st2', 'st3']]
    close = ohlc['close'].iloc[-1]
    if st.min() > close:
        sl = 0.6 * st.sort_values().iloc[0] + 0.4 * st.sort_values().iloc[1]
    elif st.max() < close:
        sl = 0.6 * st.sort_values(ascending=False).iloc[0] + 0.4 * st.sort_values(ascending=False).iloc[1]
    else:
        sl = st.mean()
    return round(sl, 1)


def update_st_direction(st_dir, ohlc, ticker):
    """Updates the supertrend direction dict in-place for the given ticker."""
    for i, col in enumerate(['st1', 'st2', 'st3']):
        if ohlc[col].iloc[-1] > ohlc['close'].iloc[-1] and ohlc[col].iloc[-2] < ohlc['close'].iloc[-2]:
            st_dir[ticker][i] = 'red'
        if ohlc[col].iloc[-1] < ohlc['close'].iloc[-1] and ohlc[col].iloc[-2] > ohlc['close'].iloc[-2]:
            st_dir[ticker][i] = 'green'


def sma_crossover_signal(ohlc, fast=5, slow=15):
    """Returns 1 (buy), -1 (sell), or 0 (no change) based on last SMA crossover."""
    d = ohlc.copy()
    d['fast'] = d['close'].rolling(window=fast).mean()
    d['slow'] = d['close'].rolling(window=slow).mean()
    d['signal'] = np.where(d['fast'] > d['slow'], 1.0, 0.0)
    position = d['signal'].diff().iloc[-1]
    return int(position)
