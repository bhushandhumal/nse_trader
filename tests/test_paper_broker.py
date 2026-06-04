"""Tests for the dry-run PaperBroker simulation."""

import logging
from unittest.mock import patch

import pandas as pd

from src.paper_broker import PaperBroker
from src.strategies.three_supertrends import run as st_run


class FakeReal:
    """Minimal stand-in for the DhanHQ client: just the constants PaperBroker reads."""
    BUY, SELL = 'BUY', 'SELL'
    MARKET, SL = 'MARKET', 'SL'
    NSE, INTRA = 'NSE', 'INTRA'


def _broker(prices, slippage=0.0):
    """PaperBroker over a mutable {sid: price} dict (sid '1' -> symbol 'AAA')."""
    return PaperBroker(
        FakeReal(),
        price_fn=lambda sid: prices.get(sid),
        slippage_pct=slippage,
        symbol_map={'1': 'AAA'},
    )


def _pos(broker, sid='1'):
    return next(p for p in broker.get_positions()['data'] if p['securityId'] == sid)


# --------------------------------------------------------------------- entries
def test_market_entry_opens_position_at_price():
    prices = {'1': 100.0}
    b = _broker(prices)
    resp = b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                         order_type='MARKET', product_type='INTRA', price=0)
    assert resp['status'] == 'success'
    p = _pos(b)
    assert p['netQty'] == 10
    assert p['tradingSymbol'] == 'AAA'


def test_market_entry_rejected_without_price():
    b = _broker({})  # no price available
    resp = b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                         order_type='MARKET', product_type='INTRA', price=0)
    assert resp['status'] == 'failure'


def test_entry_confirms_as_traded_sl_as_pending():
    prices = {'1': 100.0}
    b = _broker(prices)
    entry = b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                          order_type='MARKET', product_type='INTRA', price=0)
    sl = b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                       order_type='SL', product_type='INTRA', price=94.7, trigger_price=95.0)
    assert b.get_order_by_id(entry['data']['orderId'])['data']['orderStatus'] == 'TRADED'
    assert b.get_order_by_id(sl['data']['orderId'])['data']['orderStatus'] == 'PENDING'


# ----------------------------------------------------------------- trailing SL
def test_modify_sl_updates_trigger_and_logs(caplog):
    prices = {'1': 100.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)
    sl = b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                       order_type='SL', product_type='INTRA', price=94.7, trigger_price=95.0)
    oid = sl['data']['orderId']

    import logging
    with caplog.at_level(logging.INFO):
        resp = b.modify_order(order_id=oid, quantity=10, price=96.7, trigger_price=97.0)
    assert resp['status'] == 'success'
    assert any('SL trail' in r.message for r in caplog.records)
    # the resting order now carries the trailed trigger
    order = next(o for o in b.get_order_list()['data'] if o['orderId'] == oid)
    assert order['trigger'] == 97.0


def test_modify_unknown_order_fails():
    b = _broker({'1': 100.0})
    assert b.modify_order(order_id='nope', trigger_price=99.0)['status'] == 'failure'


# --------------------------------------------------------------- stop triggers
def test_long_stop_triggers_and_books_loss():
    prices = {'1': 100.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)   # long @ 100
    b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                  order_type='SL', product_type='INTRA', price=94.7, trigger_price=95.0)

    prices['1'] = 94.0          # drops through the stop
    p = _pos(b)                 # get_positions() sweeps -> triggers the stop
    assert p['netQty'] == 0
    assert p['realizedProfit'] == round((95.0 - 100.0) * 10, 2)   # -50


def test_short_stop_triggers_and_books_loss():
    prices = {'1': 100.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)   # short @ 100
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='SL', product_type='INTRA', price=105.3, trigger_price=105.0)

    prices['1'] = 106.0         # rises through the stop
    p = _pos(b)
    assert p['netQty'] == 0
    assert p['realizedProfit'] == round((100.0 - 105.0) * 10, 2)   # -50


def test_stop_not_triggered_while_price_inside():
    prices = {'1': 100.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)
    b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                  order_type='SL', product_type='INTRA', price=94.7, trigger_price=95.0)
    prices['1'] = 103.0
    p = _pos(b)
    assert p['netQty'] == 10
    assert p['unrealizedProfit'] == round((103.0 - 100.0) * 10, 2)   # +30


# ------------------------------------------------------------------ square-off
def test_square_off_closes_and_books_profit():
    prices = {'1': 100.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)   # long @ 100
    prices['1'] = 108.0
    # closing market order (square_off_all places the opposite side)
    b.place_order(security_id='1', transaction_type='SELL', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)
    p = _pos(b)
    assert p['netQty'] == 0
    assert p['realizedProfit'] == round((108.0 - 100.0) * 10, 2)       # +80


def test_winning_long_realized_pnl():
    prices = {'1': 50.0}
    b = _broker(prices)
    b.place_order(security_id='1', transaction_type='BUY', quantity=4,
                  order_type='MARKET', product_type='INTRA', price=0)
    b.place_order(security_id='1', transaction_type='SELL', quantity=4,
                  order_type='SL', product_type='INTRA', price=47.3, trigger_price=47.5)
    # price runs up, then we square off at market
    prices['1'] = 60.0
    b.place_order(security_id='1', transaction_type='SELL', quantity=4,
                  order_type='MARKET', product_type='INTRA', price=0)
    assert _pos(b)['realizedProfit'] == round((60.0 - 50.0) * 4, 2)    # +40


# --------------------------------------------------------------------- slippage
def test_slippage_applied_adversely():
    prices = {'1': 100.0}
    b = _broker(prices, slippage=0.01)   # 1%
    b.place_order(security_id='1', transaction_type='BUY', quantity=10,
                  order_type='MARKET', product_type='INTRA', price=0)
    # bought 1% higher than 100 -> entry 101; mark at 100 -> small loss
    assert _pos(b)['unrealizedProfit'] == round((100.0 - 101.0) * 10, 2)  # -10


# --------------------------------------------------------- delegation to client
def test_unknown_attr_delegates_to_real_client():
    b = _broker({'1': 100.0})
    # FakeReal has no such method; add one and confirm pass-through
    b._real.ohlc_data = lambda **kw: {'status': 'success'}
    assert b.ohlc_data(securities={})['status'] == 'success'


# ----------------------------------------------- integration: run() trails the SL
def _fake_ohlc(close=500.0, n=20):
    idx = pd.date_range('2026-01-01 09:15', periods=n, freq='5min', name='date')
    return pd.DataFrame({'open': close, 'high': close, 'low': close,
                         'close': close, 'volume': 1000}, index=idx)


def test_run_against_paper_broker_trails_the_stop(caplog):
    """End-to-end: the real run() -> place_sl_order / modify_sl_order path executes
    against the PaperBroker, so the protective stop is set on entry and TRAILS on
    the next cycle — the behaviour that never fired in the old log-only dry-run.
    """
    prices = {'SEC1': 500.0}
    broker = PaperBroker(FakeReal(), price_fn=lambda sid: prices.get(sid),
                         symbol_map={'SEC1': 'BHEL'})
    state = {'st_dir': {'BHEL': ['None'] * 3}, 'prev_signals': {'BHEL': 'hold'}, 'trades': []}

    base = ('src.strategies.three_supertrends.', 'src.orders.')

    def _run_cycle(sl_value):
        with patch('src.strategies.three_supertrends.instrument_lookup', return_value='SEC1'), \
             patch('src.strategies.three_supertrends.get_tick_size', return_value=0.05), \
             patch('src.strategies.three_supertrends.fetch_ohlc_incremental', return_value=_fake_ohlc()), \
             patch('src.strategies.three_supertrends.signal', return_value={'action': 'buy', 'sl': sl_value}), \
             patch('src.strategies.three_supertrends.time.sleep'), \
             patch('src.orders.time.sleep'):
            st_run(broker, object(), ['BHEL'], 100_000, state, dry_run=False)

    # Cycle 1: fresh buy -> entry fills, protective stop SET at 490.
    _run_cycle(490.0)
    pos = next(p for p in broker.get_positions()['data'] if p['tradingSymbol'] == 'BHEL')
    assert pos['netQty'] == int(100_000 / 500.0)            # position opened
    sl_orders = [o for o in broker.get_order_list()['data'] if o['orderType'] == 'SL']
    assert len(sl_orders) == 1 and sl_orders[0]['trigger'] == 490.0

    # Cycle 2: still long, signal unchanged -> the stop TRAILS up to 492.
    with caplog.at_level(logging.INFO):
        _run_cycle(492.0)
    assert any('SL trail' in r.message for r in caplog.records)
    sl_orders = [o for o in broker.get_order_list()['data'] if o['orderStatus'] == 'PENDING']
    assert sl_orders[0]['trigger'] == 492.0                  # stop moved, position still open
    assert len(state['trades']) == 1                         # no duplicate entry
