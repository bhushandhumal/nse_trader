import logging

# TODO (multi-broker): move Dhan-specific constants (dhan.BUY, dhan.STOP_LOSS, etc.)
# behind a BaseBroker.place_sl_order() interface so strategies stay broker-agnostic.


def place_market_order(dhan, security_id, buy_sell, quantity, dry_run=False):
    """Places an intraday MARKET order."""
    if dry_run:
        logging.info(f"[DRY RUN] place_market_order {buy_sell} {quantity} security={security_id}")
        return None
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
        logging.info(f"Market order placed: {resp.get('data', {}).get('orderId')}")
        return resp
    except Exception as e:
        logging.error(f"Market order failed: {e}")
        return None


def place_sl_order(dhan, security_id, buy_sell, quantity, sl_price, dry_run=False):
    """Places an intraday entry (MARKET) + protective STOP_LOSS order pair.

    Returns the entry order_id string on success, None on failure or dry run.
    """
    if dry_run:
        logging.info(f"[DRY RUN] place_sl_order {buy_sell} {quantity} @ SL {sl_price} security={security_id}")
        return None

    entry_type = dhan.BUY  if buy_sell == 'buy'  else dhan.SELL
    sl_type    = dhan.SELL if buy_sell == 'buy'  else dhan.BUY

    # Fix 2: only place SL order if entry order is confirmed accepted
    entry_resp = dhan.place_order(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=entry_type,
        quantity=quantity,
        order_type=dhan.MARKET,
        product_type=dhan.INTRA,
        price=0,
    )
    if not entry_resp or entry_resp.get('status') != 'success':
        logging.error(f"Entry order rejected for security={security_id}: {entry_resp}. SL order NOT placed.")
        return None
    order_id = entry_resp.get('data', {}).get('orderId')
    logging.info(f"Entry order placed: {order_id}")

    sl_resp = dhan.place_order(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=sl_type,
        quantity=quantity,
        order_type=dhan.SL,
        product_type=dhan.INTRA,
        price=sl_price,
        trigger_price=sl_price,
    )
    if not sl_resp or sl_resp.get('status') != 'success':
        logging.error(f"SL order failed for security={security_id}: {sl_resp}. Position is unprotected — exit manually!")
    else:
        logging.info(f"SL order placed: {sl_resp.get('data', {}).get('orderId')} @ {sl_price}")

    return order_id


def modify_sl_order(dhan, order_id, quantity, price, dry_run=False):
    """Moves an existing STOP_LOSS order to a new price."""
    if dry_run:
        logging.info(f"[DRY RUN] modify_sl_order order={order_id} qty={quantity} price={price}")
        return

    dhan.modify_order(
        order_id=order_id,
        order_type=dhan.SL,
        leg_name='',
        quantity=quantity,
        price=price,
        trigger_price=price,
        disclosed_quantity=0,
        validity='DAY',
    )


def square_off_all(dhan, dry_run=False):
    """Cancels all pending intraday orders then closes all open intraday positions at market.

    Call this before 3:20 PM to avoid broker auto-square-off at an arbitrary price.
    """
    # Step 1: cancel all pending/transit intraday orders first so they don't
    # interfere with the closing market orders below.
    try:
        orders = dhan.get_order_list().get('data', []) or []
        for order in orders:
            if order.get('orderStatus') not in ('PENDING', 'TRANSIT'):
                continue
            if order.get('productType') != 'INTRA':
                continue
            order_id = order['orderId']
            if dry_run:
                logging.info(f"[DRY RUN] Cancel order {order_id} ({order.get('tradingSymbol')})")
            else:
                try:
                    dhan.cancel_order(order_id=order_id)
                    logging.info(f"Cancelled order {order_id} ({order.get('tradingSymbol')})")
                except Exception as e:
                    logging.error(f"Failed to cancel order {order_id}: {e}")
    except Exception as e:
        logging.error(f"square_off_all: could not fetch order list: {e}")

    # Step 2: close every open intraday position with a market order.
    try:
        positions = dhan.get_positions().get('data', []) or []
        for pos in positions:
            qty = pos.get('netQty', 0)
            if qty == 0:
                continue
            symbol      = pos.get('tradingSymbol', '?')
            security_id = str(pos.get('securityId', ''))
            side        = 'sell' if qty > 0 else 'buy'
            abs_qty     = abs(qty)
            if not security_id:
                logging.error(f"square_off_all: no securityId for {symbol}, skip.")
                continue
            if dry_run:
                logging.info(f"[DRY RUN] Square off {side} {abs_qty} x {symbol}")
            else:
                place_market_order(dhan, security_id, side, abs_qty)
    except Exception as e:
        logging.error(f"square_off_all: could not fetch positions: {e}")
