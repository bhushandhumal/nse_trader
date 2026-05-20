def place_market_order(kite, symbol, transaction_type, quantity):
    """Places an intraday MIS market order."""
    try:
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product=kite.PRODUCT_MIS,
            order_type=kite.ORDER_TYPE_MARKET,
        )
        print(f"Order placed: {order_id}")
        return order_id
    except Exception as e:
        print(f"Order failed for {symbol}: {e}")
        return None


def place_sl_order(kite, symbol, buy_sell, quantity, sl_price):
    """Places an intraday entry + stop-loss order pair."""
    if buy_sell == 'buy':
        entry_type = kite.TRANSACTION_TYPE_BUY
        sl_type = kite.TRANSACTION_TYPE_SELL
    else:
        entry_type = kite.TRANSACTION_TYPE_SELL
        sl_type = kite.TRANSACTION_TYPE_BUY

    kite.place_order(
        tradingsymbol=symbol,
        exchange=kite.EXCHANGE_NSE,
        transaction_type=entry_type,
        quantity=quantity,
        order_type=kite.ORDER_TYPE_MARKET,
        product=kite.PRODUCT_MIS,
        variety=kite.VARIETY_REGULAR,
    )
    kite.place_order(
        tradingsymbol=symbol,
        exchange=kite.EXCHANGE_NSE,
        transaction_type=sl_type,
        quantity=quantity,
        order_type=kite.ORDER_TYPE_SL,
        price=sl_price,
        trigger_price=sl_price,
        product=kite.PRODUCT_MIS,
        variety=kite.VARIETY_REGULAR,
    )


def modify_sl_order(kite, order_id, price):
    """Modifies an existing SL order to a new price."""
    kite.modify_order(
        order_id=order_id,
        price=price,
        trigger_price=price,
        order_type=kite.ORDER_TYPE_SL,
        variety=kite.VARIETY_REGULAR,
    )
