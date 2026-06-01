import time
import logging

# TODO (multi-broker): move Dhan-specific constants (dhan.BUY, dhan.STOP_LOSS, etc.)
# behind a BaseBroker.place_sl_order() interface so strategies stay broker-agnostic.

# Dhan returns status='success' when it ACCEPTS a submission, but the exchange can
# REJECT the order milliseconds later (tick size, circuit limit, ...). After placing
# we poll the order status this many times to catch that rejection.
_CONFIRM_ATTEMPTS = 3
_CONFIRM_DELAY    = 1.0  # seconds between polls (lets the exchange respond)
_OK_STATUSES      = {'TRADED', 'PART_TRADED', 'PENDING', 'TRIGGERED'}


def _order_status(dhan, order_id):
    """Returns (orderStatus, reason) for an order id, or ('', '') if unavailable."""
    try:
        resp = dhan.get_order_by_id(order_id)
    except Exception as e:
        logging.warning(f"Could not fetch status for order {order_id}: {e}")
        return '', ''
    data = (resp or {}).get('data')
    if isinstance(data, list):
        data = data[0] if data else {}
    data = data or {}
    return (data.get('orderStatus', ''),
            data.get('omsErrorDescription') or data.get('remarks') or '')


def _confirm_accepted(dhan, order_id):
    """Polls an order after submission to catch exchange rejection that happens
    *after* Dhan's submission 'success' (the silent naked-position trap).

    Returns (ok, status, reason); ok is False only when the exchange REJECTED it.
    Ambiguous/unknown status after all polls is treated as ok (no false alarms).
    """
    status, reason = '', ''
    for _ in range(_CONFIRM_ATTEMPTS):
        time.sleep(_CONFIRM_DELAY)
        status, reason = _order_status(dhan, order_id)
        if status == 'REJECTED':
            return False, status, reason
        if status in _OK_STATUSES:
            return True, status, reason
    return True, status, reason


def verify_order_placement(dhan, instrument_df, tickers):
    """Preflight check run before the trading loop: place a tiny, non-marketable
    LIMIT BUY and immediately cancel it, to confirm the broker will accept live
    orders. Catches the DH-905 'Invalid IP' / stale-token class of failure BEFORE
    a 'live' session silently rejects every real signal.

    The order is priced ~2% below LTP (won't fill) and cancelled at once, so it
    never executes and costs nothing.

    Returns True if placement works (or fails only for a non-IP reason such as a
    price band), False if blocked by Invalid IP / auth / connectivity.
    """
    from src.data import instrument_lookup, fetch_ltp, get_tick_size

    for ticker in tickers:
        security_id = instrument_lookup(instrument_df, ticker)
        if security_id is None:
            continue
        ltp = fetch_ltp(dhan, instrument_df, ticker)
        if not ltp:
            continue

        tick = get_tick_size(instrument_df, ticker)
        limit_price = _round_tick(ltp * 0.98, tick)  # 2% under LTP, on the instrument tick
        logging.info(f"Preflight: verifying order placement via non-fill LIMIT BUY "
                     f"1 {ticker} @ {limit_price} (LTP {ltp})...")
        try:
            resp = dhan.place_order(
                security_id=security_id,
                exchange_segment=dhan.NSE,
                transaction_type=dhan.BUY,
                quantity=1,
                order_type=dhan.LIMIT,
                product_type=dhan.INTRA,
                price=limit_price,
            )
        except Exception as e:
            logging.error(f"Preflight order check raised an exception: {e}")
            return False

        if resp and resp.get('status') == 'success':
            order_id = resp.get('data', {}).get('orderId')
            logging.info(f"Preflight OK: order accepted (orderId={order_id}); cancelling test order.")
            try:
                dhan.cancel_order(order_id=order_id)
            except Exception as e:
                logging.warning(f"Preflight: could not cancel test order {order_id}: {e}. "
                                "Check your order book and cancel manually if still pending.")
            return True

        text = str(resp)
        if 'DH-905' in text or 'Invalid IP' in text:
            logging.error(f"Preflight FAILED: order rejected for Invalid IP (DH-905): {resp}")
            return False
        # Reached the exchange but refused for another reason (e.g. price band) —
        # auth/IP are fine, so don't block trading.
        logging.warning(f"Preflight: test order rejected for a non-IP reason: {resp}. "
                        "Auth/IP appear OK; proceeding.")
        return True

    logging.warning("Preflight: could not price a test order for any ticker "
                    "(market closed / no LTP). Skipping the check.")
    return True


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


def _round_tick(price, tick=0.05):
    """Rounds a price to the nearest exchange tick (NSE equity = 0.05)."""
    return round(round(price / tick) * tick, 2)


def _sl_trigger_and_limit(sl_price, buy_sell, tick=0.05):
    """Returns (trigger_price, limit_price) for a protective STOP_LOSS (limit) order.

    Dhan rejects price == trigger (DH-906) and does not accept SL-Market here, so we
    use an SL limit order with the limit offset ~0.3% (>= 1 tick) from the trigger in
    the fill direction — lenient enough to fill when the stop triggers:
      - protecting a LONG  (entry 'buy')  -> SELL stop, limit BELOW trigger
      - protecting a SHORT (entry 'sell') -> BUY  stop, limit ABOVE trigger

    Both prices are rounded to the instrument's `tick` (in rupees); a price that is
    not a multiple of the tick is rejected by the exchange (EXCH:16283).
    """
    trigger = _round_tick(sl_price, tick)
    buf     = max(tick, _round_tick(sl_price * 0.003, tick))
    limit   = trigger - buf if buy_sell == 'buy' else trigger + buf
    return trigger, _round_tick(limit, tick)


def place_sl_order(dhan, security_id, buy_sell, quantity, sl_price, tick_size=0.05, dry_run=False):
    """Places an intraday entry (MARKET) + protective STOP_LOSS order pair.

    `tick_size` is the instrument's rupee tick; the SL trigger/limit are rounded to
    it so the exchange accepts them.

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

    # Confirm the exchange actually accepted the entry (submission 'success' is not
    # acceptance). If it was rejected post-submission, no position exists -> no SL.
    ok, status, reason = _confirm_accepted(dhan, order_id)
    if not ok:
        logging.error(f"Entry order {order_id} REJECTED by exchange ({reason}). "
                      "No position opened; SL not placed.")
        return None
    logging.info(f"Entry order placed: {order_id} (status={status})")

    # SL leg: STOP_LOSS limit order with the limit offset from the trigger so Dhan
    # accepts it (price == trigger is rejected with DH-906; SL-Market is rejected too).
    sl_trigger, sl_limit = _sl_trigger_and_limit(sl_price, buy_sell, tick_size)
    sl_resp = dhan.place_order(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=sl_type,
        quantity=quantity,
        order_type=dhan.SL,
        product_type=dhan.INTRA,
        price=sl_limit,
        trigger_price=sl_trigger,
    )
    if not sl_resp or sl_resp.get('status') != 'success':
        logging.error(f"SL order failed for security={security_id}: {sl_resp}. Position is UNPROTECTED — exit manually!")
        return order_id

    sl_id = sl_resp.get('data', {}).get('orderId')
    # Confirm the exchange accepted the SL — a submission 'success' that the exchange
    # later REJECTS would leave the position silently unprotected.
    ok, status, reason = _confirm_accepted(dhan, sl_id)
    if not ok:
        logging.error(f"SL order {sl_id} REJECTED by exchange ({reason}). "
                      "Position is UNPROTECTED — exit manually!")
    else:
        logging.info(f"SL order placed: {sl_id} @ {sl_trigger} (status={status})")

    return order_id


def modify_sl_order(dhan, order_id, quantity, sl_price, buy_sell, tick_size=0.05, dry_run=False):
    """Moves an existing STOP_LOSS (limit) order to a new stop level.

    `sl_price` is the new stop (trigger) level; `buy_sell` is the original entry
    side ('buy' for a long, 'sell' for a short) so the limit price is offset in the
    correct direction; `tick_size` is the instrument's rupee tick for rounding
    (see place_sl_order / _sl_trigger_and_limit).
    """
    if dry_run:
        logging.info(f"[DRY RUN] modify_sl_order order={order_id} qty={quantity} sl={sl_price}")
        return

    sl_trigger, sl_limit = _sl_trigger_and_limit(sl_price, buy_sell, tick_size)
    dhan.modify_order(
        order_id=order_id,
        order_type=dhan.SL,
        leg_name='',
        quantity=quantity,
        price=sl_limit,
        trigger_price=sl_trigger,
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
