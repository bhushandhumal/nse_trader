import logging
import pandas as pd
from src.data import fetch_ohlc, instrument_lookup
from src.indicators import supertrend, sl_price, update_st_direction
from src.orders import place_sl_order, modify_sl_order

# Dhan order statuses for an SL order waiting to be triggered
_PENDING_STATUSES = {'PENDING', 'TRANSIT'}


def signal(ohlc, st_dir, ticker):
    """Returns the market signal for the current bar.

    ohlc must already have st1, st2, st3 columns computed.
    Mutates st_dir in place (crossover tracking).
    Returns {'action': 'buy'|'sell'|'hold', 'sl': float|None}.
    sl is None only when supertrend has not yet initialised (NaN values).
    """
    if len(ohlc) < 2 or ohlc[['st1', 'st2', 'st3']].iloc[-1].isna().any():
        return {'action': 'hold', 'sl': None}

    update_st_direction(st_dir, ohlc, ticker)
    current_sl = sl_price(ohlc)

    all_green = st_dir[ticker] == ['green', 'green', 'green']
    all_red   = st_dir[ticker] == ['red',   'red',   'red'  ]

    if all_green:
        return {'action': 'buy',  'sl': current_sl}
    elif all_red:
        return {'action': 'sell', 'sl': current_sl}
    else:
        return {'action': 'hold', 'sl': current_sl}


def run(dhan, instrument_df, tickers, capital, st_dir, dry_run=False):
    """One pass of the three-supertrend strategy across all tickers.

    st_dir: dict mapping ticker -> ['None'|'green'|'red', ...] x3, mutated in place.
    """
    try:
        positions = dhan.get_positions().get('data', [])
    except Exception:
        logging.error("Failed to fetch positions, skipping cycle.")
        return

    try:
        orders = dhan.get_order_list().get('data', [])
    except Exception:
        logging.error("Failed to fetch orders, skipping cycle.")
        return

    pos_map = {p['tradingSymbol']: p['netQty'] for p in positions}
    ord_df  = pd.DataFrame(orders) if orders else pd.DataFrame()

    for ticker in tickers:
        logging.info(f"Processing {ticker}...")
        try:
            security_id = instrument_lookup(instrument_df, ticker)
            if security_id is None:
                logging.warning(f"Skipping {ticker}: security_id not found.")
                continue

            ohlc = fetch_ohlc(dhan, instrument_df, ticker, '5minute', 4)
            ohlc['st1'] = supertrend(ohlc, 7, 3)
            ohlc['st2'] = supertrend(ohlc, 10, 3)
            ohlc['st3'] = supertrend(ohlc, 11, 2)

            # Fix 1: guard against zero quantity when capital < stock price
            quantity = min(int(capital / ohlc['close'].iloc[-1]), 1000)
            if quantity < 1:
                logging.warning(f"Skipping {ticker}: quantity=0 (capital ₹{capital} < price ₹{ohlc['close'].iloc[-1]:.1f})")
                continue

            sig = signal(ohlc, st_dir, ticker)
            if sig['sl'] is None:
                logging.warning(f"Skipping {ticker}: supertrend not yet initialised (NaN in last candle).")
                continue

            has_position = pos_map.get(ticker, 0) != 0

            if has_position and not ord_df.empty:
                pending = ord_df[
                    (ord_df['tradingSymbol'] == ticker) &
                    (ord_df['orderStatus'].isin(_PENDING_STATUSES))
                ]
                if not pending.empty:
                    row = pending.iloc[0]
                    modify_sl_order(dhan, row['orderId'], int(row['quantity']), sig['sl'], dry_run=dry_run)
            elif not has_position:
                if sig['action'] == 'buy':
                    place_sl_order(dhan, security_id, 'buy',  quantity, sig['sl'], dry_run=dry_run)
                elif sig['action'] == 'sell':
                    place_sl_order(dhan, security_id, 'sell', quantity, sig['sl'], dry_run=dry_run)

        except Exception as e:
            logging.error(f"Error for {ticker}: {e}")
