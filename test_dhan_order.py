"""One-shot test: place a tiny, non-filling LIMIT order to confirm Dhan order
placement works (i.e. the DH-905 'Invalid IP' rejection is resolved).

Strategy: place a LIMIT BUY for 1 share priced ~5% BELOW the last traded price
so it rests as PENDING and will not execute, then immediately cancel it.

  - status == 'success'  -> IP whitelist OK. Order placed (and we cancel it).
  - DH-905 / Invalid IP   -> still broken; whitelist the correct public IPv4.
  - any other rejection   -> IP passed the gateway, but order refused for some
                             other reason (still tells us the IP is fine).

Run:  & "D:\\dev\\venvs\\nse_trader_venv\\Scripts\\Activate.ps1"; python test_dhan_order.py

Safe to run while the bot is live — it reuses the same cached token, and the
order never fills (cancelled within a second).
"""
import sys
import time
import logging

sys.path.insert(0, '.')
from src.session import load_session

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# IDEA -- cheapest liquid name from today's screener (validated security_id).
# 1 share ~ Rs 14, so risk is negligible even in the unlikely event of a fill.
TEST_SYMBOL      = 'IDEA'
TEST_SECURITY_ID = '14366'


def round_tick(price, tick=0.05):
    return round(round(price / tick) * tick, 2)


def main():
    dhan = load_session()

    # 1. Last traded price, to price a non-marketable limit.
    ltp = None
    try:
        res = dhan.ohlc_data(securities={'NSE_EQ': [int(TEST_SECURITY_ID)]})
        if res.get('status') == 'success':
            # SDK nests the payload as data -> data -> NSE_EQ -> "<security_id>"
            data = res.get('data', {})
            nse = data.get('data', data).get('NSE_EQ', {})
            entry = nse.get(TEST_SECURITY_ID) or nse.get(int(TEST_SECURITY_ID))
            if entry:
                ltp = entry['last_price']
    except Exception as e:
        logging.warning(f"Could not fetch LTP: {e}")

    if not ltp:
        print("\nCould not get LTP (market may be closed / data issue). Aborting "
              "before placing a blind order.")
        return 2

    limit_price = round_tick(ltp * 0.95)   # 5% below LTP -> will not fill
    print(f"\n{TEST_SYMBOL} LTP = Rs {ltp}  ->  placing LIMIT BUY 1 @ Rs {limit_price} "
          f"(non-marketable, will be cancelled)\n")

    # 2. Place the test order.
    resp = dhan.place_order(
        security_id=TEST_SECURITY_ID,
        exchange_segment=dhan.NSE,
        transaction_type=dhan.BUY,
        quantity=1,
        order_type=dhan.LIMIT,
        product_type=dhan.INTRA,
        price=limit_price,
    )
    print(f"place_order response:\n  {resp}\n")

    status  = (resp or {}).get('status')
    remarks = (resp or {}).get('remarks', {})
    err_msg = remarks.get('error_message', '') if isinstance(remarks, dict) else str(remarks)
    err_code = remarks.get('error_code', '') if isinstance(remarks, dict) else ''

    if status == 'success':
        order_id = resp.get('data', {}).get('orderId')
        print(f"RESULT: ORDER PLACEMENT WORKS. Order accepted (orderId={order_id}).")
        print("        => Your IP whitelist fix is live. Cancelling the test order...")
        time.sleep(1)
        try:
            cancel = dhan.cancel_order(order_id=order_id)
            print(f"        Cancel response: {cancel}")
        except Exception as e:
            print(f"        WARNING: could not cancel test order {order_id}: {e}")
            print("        Check your Dhan order book and cancel it manually if still pending.")
        return 0

    if 'DH-905' in str(resp) or 'Invalid IP' in str(resp):
        print("RESULT: STILL BLOCKED -- DH-905 'Invalid IP'.")
        print("        => The IP Dhan sees is NOT whitelisted. Whitelist your public IPv4")
        print("           (run a public-IP check from this machine) and try again.")
        return 1

    print(f"RESULT: Order was rejected, but NOT for Invalid IP "
          f"(code={err_code!r} msg={err_msg!r}).")
    print("        => This means the IP whitelist PASSED; the order failed for another "
          "reason (e.g. price band / market closed). Order placement itself is working.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
