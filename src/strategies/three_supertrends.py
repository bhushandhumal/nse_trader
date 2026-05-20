import pandas as pd
from src.data import fetch_ohlc
from src.indicators import supertrend, sl_price, update_st_direction
from src.orders import place_sl_order, modify_sl_order


def run(kite, instrument_df, tickers, capital, st_dir):
    """One pass of the three-supertrend strategy across all tickers.

    st_dir: dict mapping ticker -> ['None'|'green'|'red', ...] x3, mutated in place.
    """
    try:
        pos_df = pd.DataFrame(kite.positions()['day'])
    except Exception:
        print("Failed to fetch positions, skipping cycle.")
        return

    try:
        ord_df = pd.DataFrame(kite.orders())
    except Exception:
        print("Failed to fetch orders, skipping cycle.")
        return

    for ticker in tickers:
        print(f"Processing {ticker}...")
        try:
            ohlc = fetch_ohlc(kite, instrument_df, ticker, '5minute', 4)
            ohlc['st1'] = supertrend(ohlc, 7, 3)
            ohlc['st2'] = supertrend(ohlc, 10, 3)
            ohlc['st3'] = supertrend(ohlc, 11, 2)
            update_st_direction(st_dir, ohlc, ticker)

            quantity = min(int(capital / ohlc['close'].iloc[-1]), 1000)
            all_green = st_dir[ticker] == ['green', 'green', 'green']
            all_red = st_dir[ticker] == ['red', 'red', 'red']
            current_sl = sl_price(ohlc)

            has_position = (
                len(pos_df.columns) != 0 and
                ticker in pos_df['tradingsymbol'].tolist() and
                pos_df[pos_df['tradingsymbol'] == ticker]['quantity'].values[0] != 0
            )

            if has_position:
                order_id = ord_df.loc[
                    (ord_df['tradingsymbol'] == ticker) &
                    (ord_df['status'].isin(['TRIGGER PENDING', 'OPEN']))
                ]['order_id'].values[0]
                modify_sl_order(kite, order_id, current_sl)
            else:
                if all_green:
                    place_sl_order(kite, ticker, 'buy', quantity, current_sl)
                elif all_red:
                    place_sl_order(kite, ticker, 'sell', quantity, current_sl)

        except Exception as e:
            print(f"Error for {ticker}: {e}")
