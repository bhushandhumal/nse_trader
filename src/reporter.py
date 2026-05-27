import logging
import datetime as dt


def print_eod_report(strategy_name, state, dhan):
    """Prints a strategy's EOD performance report.

    Fetches final positions from Dhan for realized/unrealized P&L,
    filtered to only the tickers this strategy actually traded today.
    """
    trades = state.get('trades', [])
    today  = dt.date.today()

    sep = '=' * 58
    print(f"\n{sep}")
    print(f"  EOD Report: {strategy_name}  -  {today}")
    print(f"{sep}")

    if not trades:
        print("  No trades placed today.")
        print(f"{sep}\n")
        return

    print(f"\n  {'Ticker':<12} {'Side':<5} {'Qty':>5}  {'SL Price':>10}  {'Time':>5}  {'Order ID'}")
    print(f"  {'-'*54}")
    for t in trades:
        oid = t.get('order_id') or 'DRY RUN'
        print(f"  {t['ticker']:<12} {t['action'].upper():<5} {t['qty']:>5}"
              f"  Rs{t['sl_price']:>9.1f}  {t['time']:>5}  {oid}")

    # --- P&L from Dhan positions ---
    traded_tickers = {t['ticker'] for t in trades}
    positions = []
    try:
        positions = dhan.get_positions().get('data', []) or []
        relevant  = [p for p in positions if p.get('tradingSymbol') in traded_tickers]
    except Exception as e:
        logging.error(f"EOD report: could not fetch positions: {e}")
        relevant = []

    if relevant:
        print(f"\n  {'Ticker':<12} {'Net Qty':>7}  {'Realized':>12}  {'Unrealized':>12}")
        print(f"  {'-'*54}")
        total_realized   = 0.0
        total_unrealized = 0.0
        for p in relevant:
            sym  = p.get('tradingSymbol', '?')
            qty  = p.get('netQty', 0)
            rpnl = float(p.get('realizedProfit', 0))
            upnl = float(p.get('unrealizedProfit', 0))
            total_realized   += rpnl
            total_unrealized += upnl
            print(f"  {sym:<12} {qty:>7}  Rs{rpnl:>11.1f}  Rs{upnl:>11.1f}")

        net = total_realized + total_unrealized
        print(f"\n  Trades today:  {len(trades)}")
        print(f"  Realized P&L:  Rs{total_realized:>10.1f}")
        print(f"  Unrealized:    Rs{total_unrealized:>10.1f}")
        print(f"  Net P&L:       Rs{net:>10.1f}")
    else:
        print(f"\n  Trades placed: {len(trades)}")
        if not positions:
            print("  (No open positions - all squared off or no data available)")

    print(f"{sep}\n")
