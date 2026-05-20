# TODO (multi-broker): move Dhan-specific constants (dhan.BUY, dhan.STOP_LOSS, etc.)
# behind a BaseBroker.place_sl_order() interface so strategies stay broker-agnostic.


def place_market_order(dhan, security_id, buy_sell, quantity):
    """Places an intraday MARKET order."""
    try:
        resp = dhan.place_order(
            security_id=security_id,
            exchange_segment=dhan.NSE,
            transaction_type=dhan.BUY if buy_sell == 'buy' else dhan.SELL,
            quantity=quantity,
            order_type=dhan.MARKET,
            product_type=dhan.INTRA,
            price=0,
        )
        print(f"Market order placed: {resp.get('data', {}).get('orderId')}")
        return resp
    except Exception as e:
        print(f"Market order failed: {e}")
        return None


def place_sl_order(dhan, security_id, buy_sell, quantity, sl_price):
    """Places an intraday entry (MARKET) + protective STOP_LOSS order pair."""
    entry_type = dhan.BUY  if buy_sell == 'buy'  else dhan.SELL
    sl_type    = dhan.SELL if buy_sell == 'buy'  else dhan.BUY

    dhan.place_order(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=entry_type,
        quantity=quantity,
        order_type=dhan.MARKET,
        product_type=dhan.INTRA,
        price=0,
    )
    dhan.place_order(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=sl_type,
        quantity=quantity,
        order_type=dhan.STOP_LOSS,
        product_type=dhan.INTRA,
        price=sl_price,
        trigger_price=sl_price,
    )


def modify_sl_order(dhan, order_id, quantity, price):
    """Moves an existing STOP_LOSS order to a new price."""
    dhan.modify_order(
        order_id=order_id,
        order_type=dhan.STOP_LOSS,
        leg_name='',
        quantity=quantity,
        price=price,
        trigger_price=price,
        disclosed_quantity=0,
        validity='DAY',
    )
