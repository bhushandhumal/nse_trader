def print_report(trades: list, ticker: str, interval: str, from_date: str, capital: int):
    header = (
        f"Ticker: {ticker}  |  Interval: {interval}  |  "
        f"From: {from_date}  |  Capital: ₹{capital:,}"
    )
    width = max(len(header), 108)
    sep = '─' * width

    print()
    print(header)
    print(sep)

    if not trades:
        print("  No trades generated.")
        print(sep)
        return

    # Table
    print(
        f"  {'#':>3}  {'Entry':^20}  {'Exit':^20}  "
        f"{'Side':<5}  {'Entry px':>8}  {'Exit px':>8}  {'Qty':>4}  {'P&L':>10}"
    )
    print(
        f"  {'':->3}  {'':->20}  {'':->20}  "
        f"{'':->5}  {'':->8}  {'':->8}  {'':->4}  {'':->10}"
    )
    for n, t in enumerate(trades, 1):
        flag = '*' if t.get('open') else ' '
        side = 'LONG' if t['side'] == 'buy' else 'SHORT'
        pnl_str = f"₹{t['pnl']:>+,.0f}"
        entry_str = str(t['entry_time'])[:19]
        exit_str  = str(t['exit_time'])[:19]
        print(
            f"  {n:>3}  {entry_str:<20}  {exit_str:<20}  "
            f"{side:<5}  {t['entry_price']:>8.2f}  {t['exit_price']:>8.2f}  "
            f"{t['qty']:>4}  {pnl_str:>10}{flag}"
        )

    print(sep)

    closed        = [t for t in trades if not t.get('open')]
    wins          = [t for t in closed if t['pnl'] > 0]
    losses        = [t for t in closed if t['pnl'] <= 0]
    total_pnl     = sum(t['pnl'] for t in trades)
    gross_profit  = sum(t['pnl'] for t in wins)
    gross_loss    = abs(sum(t['pnl'] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else float('inf')
    win_rate      = 100 * len(wins) / len(closed) if closed else 0.0
    avg_trade     = total_pnl / len(trades) if trades else 0.0

    cum = peak = max_dd = 0.0
    for t in trades:
        cum += t['pnl']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    pf_str = f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞"
    print(
        f"  Trades: {len(trades)}  |  "
        f"Wins: {len(wins)} ({win_rate:.1f}%)  |  "
        f"Total P&L: ₹{total_pnl:+,.0f}  |  "
        f"Profit factor: {pf_str}"
    )
    print(
        f"  Max drawdown: ₹{max_dd:,.0f}  |  "
        f"Avg trade: ₹{avg_trade:+,.1f}"
    )
    if any(t.get('open') for t in trades):
        print("  (* position still open at end of data, valued at last close)")
    print(sep)
    print()
