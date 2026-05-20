import pandas as pd
from src.data import fetch_ohlc, instrument_lookup
from src.indicators import supertrend, sl_price, update_st_direction
from src.orders import place_sl_order, modify_sl_order

# Dhan order statuses for an SL order waiting to be triggered
_PENDING_STATUSES = {'PENDING', 'TRANSIT'}


def run(dhan, instrument_df, tickers, capital, st_dir, dry_run=False):
    """One pass of the three-supertrend strategy across all tickers.

    st_dir: dict mapping ticker -> ['None'|'green'|'red', ...] x3, mutated in place.
    """
    try:
        positions = dhan.get_positions().get('data', [])
    except Exception:
        print("Failed to fetch positions, skipping cycle.")
        return

    try:
        orders = dhan.get_order_list().get('data', [])
    except Exception:
        print("Failed to fetch orders, skipping cycle.")
        return

    pos_map = {p['tradingSymbol']: p['netQty'] for p in positions}
    ord_df  = pd.DataFrame(orders) if orders else pd.DataFrame()

    for ticker in tickers:
        print(f"Processing {ticker}...")
        try:
            security_id = instrument_lookup(instrument_df, ticker)
            if security_id is None:
                print(f"  Skipping {ticker}: security_id not found.")
                continue

            ohlc = fetch_ohlc(dhan, instrument_df, ticker, '5minute', 4)
            ohlc['st1'] = supertrend(ohlc, 7, 3)
            ohlc['st2'] = supertrend(ohlc, 10, 3)
            ohlc['st3'] = supertrend(ohlc, 11, 2)
            update_st_direction(st_dir, ohlc, ticker)

            quantity    = min(int(capital / ohlc['close'].iloc[-1]), 1000)
            all_green   = st_dir[ticker] == ['green', 'green', 'green']
            all_red     = st_dir[ticker] == ['red',   'red',   'red'  ]
            current_sl  = sl_price(ohlc)
            has_position = pos_map.get(ticker, 0) != 0

            if has_position and not ord_df.empty:
                pending = ord_df[
                    (ord_df['tradingSymbol'] == ticker) &
                    (ord_df['orderStatus'].isin(_PENDING_STATUSES))
                ]
                if not pending.empty:
                    row = pending.iloc[0]
                    modify_sl_order(dhan, row['orderId'], int(row['quantity']), current_sl, dry_run=dry_run)
            elif not has_position:
                if all_green:
                    place_sl_order(dhan, security_id, 'buy',  quantity, current_sl, dry_run=dry_run)
                elif all_red:
                    place_sl_order(dhan, security_id, 'sell', quantity, current_sl, dry_run=dry_run)

        except Exception as e:
            print(f"  Error for {ticker}: {e}")
