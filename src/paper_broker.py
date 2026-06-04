"""In-memory paper broker for faithful dry-run trading.

The old dry-run only logged a line per order and returned None, so the strategy's
position/SL logic (which is driven by the *live* broker state) never fired: the
modify-SL branch was never reached, the protective stop never trailed, and exits
were only signal flips. That made dry-run a poor proxy for live, where trailing
the stop via modify_sl_order is the heart of the strategy.

PaperBroker fixes that by being a drop-in stand-in for the DhanHQ client. It
wraps the real client (so all market-data / quote calls and broker constants pass
straight through) and overrides only the *order* methods with an in-memory
simulation:

  * entry MARKET orders fill immediately at the latest price (+ optional slippage)
  * the protective STOP_LOSS order rests as PENDING and trails when modify_order
    is called each cycle  ← the path that never ran in the old dry-run
  * a resting stop triggers (and closes the position) when price crosses it
  * square-off closes open positions at market
  * realized / unrealized P&L is tracked per position, shaped exactly like Dhan's
    get_positions() payload so the EOD reporter prints real numbers

Because the *same* run()/orders.py code path executes (no dry_run shortcut), the
simulation exercises the live logic — only the fills are simulated.

Price source: by default the latest 5-minute close from the local OHLC cache that
the strategy already writes every cycle (no extra API calls, and the exact price
the strategy saw). Inject `price_fn` to override (e.g. live LTP, or a test stub).
"""

import time
import logging

from src.data import load_ohlc

# Simulated slippage as a fraction of price, applied adversely to every fill.
# 0.0 keeps P&L exact; bump it (e.g. 0.0005 = 5 bps) for a more conservative run.
DEFAULT_SLIPPAGE_PCT = 0.0


class PaperBroker:
    def __init__(self, real, instrument_df=None, price_fn=None,
                 slippage_pct=DEFAULT_SLIPPAGE_PCT, symbol_map=None):
        self._real = real
        self._slip = slippage_pct
        self._symbol_by_sid = symbol_map if symbol_map is not None else self._build_symbol_map(instrument_df)
        self._price_fn = price_fn or self._default_price_fn
        self._positions = {}   # sid -> {tradingSymbol, securityId, qty(signed), entry, realized}
        self._orders = []      # list of order dicts (entries + resting SLs)
        self._n = 0
        # Capture the broker's constants so we can classify orders the strategy
        # submits (transaction_type=dhan.BUY, order_type=dhan.SL, ...).
        self._BUY    = getattr(real, 'BUY', 'BUY')
        self._SELL   = getattr(real, 'SELL', 'SELL')
        self._MARKET = getattr(real, 'MARKET', 'MARKET')
        self._SL     = getattr(real, 'SL', 'SL')

    # --- everything we don't override (data calls, constants) goes to the real client ---
    def __getattr__(self, name):
        return getattr(self._real, name)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _build_symbol_map(instrument_df):
        """sid (str) -> NSE-equity trading symbol, from the scrip master."""
        if instrument_df is None:
            return {}
        try:
            mask = (
                (instrument_df['SEM_EXM_EXCH_ID'] == 'NSE') &
                (instrument_df['SEM_INSTRUMENT_NAME'] == 'EQUITY') &
                (instrument_df['SEM_SERIES'] == 'EQ')
            )
            sub = instrument_df[mask]
            return {str(s): sym for s, sym in
                    zip(sub['SEM_SMST_SECURITY_ID'], sub['SEM_TRADING_SYMBOL'])}
        except Exception:
            return {}

    def _default_price_fn(self, sid):
        sym = self._symbol_by_sid.get(sid)
        if not sym:
            return None
        df = load_ohlc(sym, '5minute')
        if df is None or df.empty:
            return None
        return float(df['close'].iloc[-1])

    def _price(self, sid):
        try:
            return self._price_fn(sid)
        except Exception as e:
            logging.warning(f"[SIM] price lookup failed for {sid}: {e}")
            return None

    def _apply_slippage(self, price, side):
        # Buy fills a touch higher, sell a touch lower — always adverse to us.
        return price * (1 + self._slip) if side == 'buy' else price * (1 - self._slip)

    def _new_id(self):
        self._n += 1
        return f"SIM{self._n}"

    def _fill(self, sid, symbol, side, qty, price):
        """Apply a fill to the net position, booking realized P&L on any reduction."""
        pos = self._positions.setdefault(
            sid, {'tradingSymbol': symbol, 'securityId': sid, 'qty': 0, 'entry': 0.0, 'realized': 0.0})
        signed = qty if side == 'buy' else -qty
        cur = pos['qty']

        if cur == 0 or (cur > 0) == (signed > 0):
            # Opening, or adding in the same direction -> weighted-average entry.
            total = abs(cur) + abs(signed)
            pos['entry'] = (pos['entry'] * abs(cur) + price * abs(signed)) / total if total else 0.0
            pos['qty'] = cur + signed
        else:
            # Reducing / closing / flipping -> realize P&L on the closed quantity.
            closing = min(abs(signed), abs(cur))
            if cur > 0:   # long closed by a sell
                pos['realized'] += (price - pos['entry']) * closing
            else:         # short closed by a buy
                pos['realized'] += (pos['entry'] - price) * closing
            pos['qty'] = cur + signed
            if pos['qty'] == 0:
                pos['entry'] = 0.0
                self._cancel_sl_for(sid)          # stop dies with the position
            elif (pos['qty'] > 0) != (cur > 0):
                pos['entry'] = price              # flipped past flat -> new leg

    def _cancel_sl_for(self, sid):
        for o in self._orders:
            if o['sid'] == sid and o['orderType'] == 'SL' and o['orderStatus'] == 'PENDING':
                o['orderStatus'] = 'CANCELLED'

    def _sweep(self):
        """Trigger any resting stop whose level the latest price has crossed."""
        for o in self._orders:
            if o['orderStatus'] != 'PENDING' or o['orderType'] != 'SL':
                continue
            sid = o['sid']
            pos = self._positions.get(sid)
            if not pos or pos['qty'] == 0:
                o['orderStatus'] = 'CANCELLED'
                continue
            px = self._price(sid)
            if px is None:
                continue
            trig = o['trigger']
            hit = (o['side'] == 'sell' and px <= trig) or (o['side'] == 'buy' and px >= trig)
            if hit:
                fill = self._apply_slippage(trig, o['side'])
                o['orderStatus'] = 'TRADED'      # set before _fill so it isn't auto-cancelled
                o['price'] = fill
                self._fill(sid, o['tradingSymbol'], o['side'], o['quantity'], fill)
                logging.info(f"[SIM] SL hit {o['tradingSymbol']} {o['side']} {o['quantity']} @ {fill:.2f}")

    # ------------------------------------------------------------------ broker API
    def place_order(self, security_id, exchange_segment=None, transaction_type=None,
                    quantity=0, order_type=None, product_type=None, price=0,
                    trigger_price=None, **kw):
        sid    = str(security_id)
        symbol = self._symbol_by_sid.get(sid, sid)
        side   = 'buy' if transaction_type == self._BUY else 'sell'
        oid    = self._new_id()

        if order_type == self._SL:
            trig = float(trigger_price if trigger_price is not None else price)
            self._orders.append({
                'orderId': oid, 'sid': sid, 'tradingSymbol': symbol, 'side': side,
                'quantity': int(quantity), 'orderType': 'SL', 'orderStatus': 'PENDING',
                'productType': 'INTRA', 'trigger': trig, 'price': float(price),
            })
            logging.info(f"[SIM] SL set {symbol} {side} {quantity} trigger={trig}")
            return {'status': 'success', 'data': {'orderId': oid}}

        # MARKET order -> fill now (entry, or a closing/square-off order).
        px = self._price(sid)
        if px is None:
            logging.warning(f"[SIM] no price for {symbol}; MARKET order not filled.")
            return {'status': 'failure', 'remarks': 'no market price', 'data': {}}
        fill = self._apply_slippage(px, side)
        self._fill(sid, symbol, side, int(quantity), fill)
        self._orders.append({
            'orderId': oid, 'sid': sid, 'tradingSymbol': symbol, 'side': side,
            'quantity': int(quantity), 'orderType': 'MARKET', 'orderStatus': 'TRADED',
            'productType': 'INTRA', 'trigger': None, 'price': fill,
        })
        logging.info(f"[SIM] fill {side} {quantity} {symbol} @ {fill:.2f}")
        return {'status': 'success', 'data': {'orderId': oid}}

    def modify_order(self, order_id, quantity=None, price=None, trigger_price=None, **kw):
        for o in self._orders:
            if o['orderId'] == order_id and o['orderStatus'] == 'PENDING':
                if trigger_price is not None:
                    o['trigger'] = float(trigger_price)
                if price is not None:
                    o['price'] = float(price)
                if quantity is not None:
                    o['quantity'] = int(quantity)
                logging.info(f"[SIM] SL trail {o['tradingSymbol']} -> trigger={o['trigger']}")
                return {'status': 'success', 'data': {'orderId': order_id}}
        return {'status': 'failure', 'remarks': 'order not pending', 'data': {}}

    def cancel_order(self, order_id, **kw):
        for o in self._orders:
            if o['orderId'] == order_id and o['orderStatus'] in ('PENDING', 'TRANSIT'):
                o['orderStatus'] = 'CANCELLED'
                logging.info(f"[SIM] cancel {o['tradingSymbol']} order {order_id}")
                return {'status': 'success', 'data': {'orderId': order_id}}
        return {'status': 'failure', 'data': {}}

    def get_order_by_id(self, order_id):
        for o in self._orders:
            if o['orderId'] == order_id:
                return {'status': 'success',
                        'data': {'orderStatus': o['orderStatus'], 'omsErrorDescription': ''}}
        return {'status': 'failure', 'data': {}}

    def get_order_list(self):
        self._sweep()
        return {'status': 'success', 'data': list(self._orders)}

    def get_positions(self):
        self._sweep()
        out = []
        for sid, pos in self._positions.items():
            px = self._price(sid)
            if pos['qty'] > 0 and px is not None:
                upnl = (px - pos['entry']) * pos['qty']
            elif pos['qty'] < 0 and px is not None:
                upnl = (pos['entry'] - px) * abs(pos['qty'])
            else:
                upnl = 0.0
            out.append({
                'tradingSymbol': pos['tradingSymbol'], 'securityId': sid,
                'netQty': pos['qty'], 'productType': 'INTRA',
                'realizedProfit': round(pos['realized'], 2),
                'unrealizedProfit': round(upnl, 2),
            })
        return {'status': 'success', 'data': out}
