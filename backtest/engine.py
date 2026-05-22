import pandas as pd
from src.indicators import supertrend
from src.strategies import three_supertrends


def run(ohlc: pd.DataFrame, ticker: str, capital: float) -> list:
    """Bar-by-bar backtest of the three-supertrend strategy.

    Entries fire at the next bar's open after a signal.
    SL exits fill at exactly the SL price (realistic — assumes price traded there).
    No re-entry on the same bar as an exit.
    Returns a list of trade dicts; open positions at end-of-data are included and
    marked with 'open': True.
    """
    df = ohlc.copy()
    df['st1'] = supertrend(df, 7, 3)
    df['st2'] = supertrend(df, 10, 3)
    df['st3'] = supertrend(df, 11, 2)

    trades = []
    position    = 0        # shares held; 0 = flat
    entry_price = None
    entry_time  = None
    entry_side  = None     # 'buy' | 'sell'
    current_sl  = None
    pending     = None     # {'side': str, 'sl': float} — execute at next bar open
    exited_bar  = -1
    st_dir      = {ticker: ['None', 'None', 'None']}

    for i in range(1, len(df)):
        bar = df.iloc[i]

        # 1. Execute pending entry at this bar's open
        if pending is not None and position == 0:
            qty = max(int(capital / bar['open']), 1)
            entry_price = bar['open']
            entry_time  = df.index[i]
            entry_side  = pending['side']
            current_sl  = pending['sl']
            position    = qty
            pending     = None

        # 2. Check SL hit (fills at sl price — realistic worst-case assumption)
        if position != 0:
            sl_hit = (
                (entry_side == 'buy'  and bar['low']  <= current_sl) or
                (entry_side == 'sell' and bar['high'] >= current_sl)
            )
            if sl_hit:
                exit_price = current_sl
                pnl = (
                    (exit_price - entry_price) if entry_side == 'buy'
                    else (entry_price - exit_price)
                ) * position
                trades.append({
                    'entry_time':  entry_time,
                    'exit_time':   df.index[i],
                    'side':        entry_side,
                    'entry_price': round(entry_price, 2),
                    'exit_price':  round(exit_price, 2),
                    'qty':         position,
                    'pnl':         round(pnl, 2),
                })
                position    = 0
                entry_price = entry_time = entry_side = current_sl = None
                exited_bar  = i

        # 3. Compute signal once per bar (updates st_dir as side effect)
        sig = three_supertrends.signal(df.iloc[:i + 1], st_dir, ticker)

        # 4. Trail SL on open position, or queue a new entry
        if position != 0:
            if sig['sl'] is not None:
                current_sl = sig['sl']
        elif exited_bar != i:
            if sig['action'] in ('buy', 'sell') and sig['sl'] is not None:
                pending = {'side': sig['action'], 'sl': sig['sl']}

    # Close any position still open at end of data (mark as open)
    if position != 0:
        exit_price = df.iloc[-1]['close']
        pnl = (
            (exit_price - entry_price) if entry_side == 'buy'
            else (entry_price - exit_price)
        ) * position
        trades.append({
            'entry_time':  entry_time,
            'exit_time':   df.index[-1],
            'side':        entry_side,
            'entry_price': round(entry_price, 2),
            'exit_price':  round(exit_price, 2),
            'qty':         position,
            'pnl':         round(pnl, 2),
            'open':        True,
        })

    return trades
