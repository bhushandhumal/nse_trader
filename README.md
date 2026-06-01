# nse_trader

An intraday trading bot for NSE (India) built on the [Dhan API](https://dhanhq.co/docs/v2/).

## Features

- **TOTP-based auth** — auto-generates a fresh Dhan access token on startup using PIN + TOTP; no manual token rotation needed
- **Three Supertrends strategy** — ATR-based trend confirmation across three parameter sets
- **Pre-market screener** — scans Nifty 200 each morning, ranks by ADX and ATR%, outputs a ready-to-paste `TICKERS=` line
- **Order-placement preflight** — on startup the bot places and cancels a tiny non-marketable order to confirm the broker will accept live orders (catches IP-whitelist / stale-token issues) *before* trading; it aborts with a clear message if blocked
- **Protected entries** — every entry is paired with a stop-loss order, priced to the instrument's real tick size, and its status is confirmed *after* submission so a rejected (unprotected) position is flagged loudly instead of silently
- **Market hours guard** — runs only during NSE session (Mon–Fri, 9:15–15:30)
- **Square-off** — closes all positions promptly at 3:15 PM (fires within seconds, beating Dhan's ~3:20 PM auto square-off)

## Project Structure

```
nse_trader/
├── .env.example                          # credential template — copy to .env and fill in
├── .env                                  # your credentials (gitignored)
├── requirements.txt
├── main.py                               # entry point
├── check_connection.py                   # verify Dhan session and API access
├── test_dhan_order.py                    # standalone order-placement check (place + cancel)
└── src/
    ├── session.py                        # TOTP login, token caching
    ├── data.py                           # fetch_ohlc, fetch_ltp, instrument_lookup, get_tick_size
    ├── indicators.py                     # atr, supertrend, sl_price
    ├── orders.py                         # verify_order_placement, place_sl_order, modify_sl_order, square_off_all
    ├── reporter.py                       # EOD trade log + P&L report
    └── strategies/
        ├── three_supertrends.py          # main intraday strategy
        └── three_supertrends_screener.py # pre-market Nifty 200 screener
```

## Setup

### 1. Clone, create a virtualenv, and install dependencies

```bash
git clone https://github.com/bhushandhumal/nse_trader.git
cd nse_trader
python -m venv .venv
# activate it:  Windows -> .venv\Scripts\Activate.ps1   |   macOS/Linux -> source .venv/bin/activate
pip install -r requirements.txt
```

> Always run the bot, screener, and tests **inside the virtualenv**. All commands
> below assume the venv is activated.

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```
DHAN_CLIENT_ID=your_dhan_client_id
DHAN_TOTP_SECRET=BASE32SECRETHERE
DHAN_PIN=your_dhan_pin

CAPITAL=1000000
TICKERS=RELIANCE,INFY,...
```

**Getting your TOTP secret:**
1. Open the Dhan app → Profile → Security → 2FA
2. Re-enable 2FA — it shows a QR code
3. Scan with an authenticator app that exposes the secret (e.g. [Aegis](https://getaegis.app/) on Android)
4. The secret is the `secret=` parameter in the `otpauth://` URL (a base32 string)

> `.env` and `.token_cache` are gitignored and will never be committed.

### 3. Verify connection

```bash
python check_connection.py
```

## Daily Workflow

### Morning (before 9:15 AM) — run the screener

```bash
python -m src.strategies.three_supertrends_screener
```

Scans all Nifty 200 stocks, filters by ADX ≥ 25 and ATR% ≥ 1.0, and prints:

```
TICKERS=HDFCBANK,RELIANCE,INFY,...
```

Paste that line into `.env`, then start the bot.

### 9:15 AM — start the bot

```bash
python main.py --dry-run   # paper trading
python main.py             # live trading
```

On startup (live mode) the bot runs an **order-placement preflight** — it places and
cancels a tiny non-marketable order to confirm the broker will accept orders, and
**aborts** if blocked (e.g. IP not whitelisted / stale token). It then runs every
5 minutes, places a protected entry (market entry + stop-loss) on supertrend
signals, trails the stop, and squares off all positions at 3:15 PM.

You can also run the order-placement check on its own at any time:

```bash
python test_dhan_order.py   # places a non-fillable order, then cancels it (costs nothing)
```

## Configuration

All config lives in `.env`:

```
CAPITAL=1000000        # max capital per position (INR)
TICKERS=RELIANCE,INFY  # comma-separated list (use screener output)
```

## Strategy — Three Supertrends

Places an intraday entry + stop-loss order when all three supertrend indicators align (all green = buy, all red = sell). Re-entry is blocked until the signal transitions through `hold`, preventing duplicate orders.

| Parameter  | ST1 | ST2 | ST3 |
|------------|-----|-----|-----|
| ATR period | 7   | 10  | 11  |
| Multiplier | 3   | 3   | 2   |

Position size: `qty = min(int(CAPITAL / price), 1000)` — so a stock priced above
`CAPITAL` is skipped (quantity 0).

### Stop-loss

The stop is derived from the three supertrend lines on the last 5-minute candle
(`sl_price` in `indicators.py`):

- **Long** (all lines below price): `SL = 0.6·(highest line) + 0.4·(2nd-highest)` → below entry
- **Short** (all lines above price): `SL = 0.6·(lowest line) + 0.4·(2nd-lowest)` → above entry
- **Lines straddle price**: `SL = mean(lines)`

Because each supertrend line is `midpoint ± multiplier·ATR`, the stop sits roughly
**2.4·ATR** from entry. It is placed as a stop-**limit** order (the limit offset from
the trigger and rounded to the instrument's tick) and **trailed** every cycle.

### Estimating max loss

Per position, `risk ≈ qty · |entry − SL| ≈ CAPITAL · (SL distance / price)`. Since the
SL distance is ~2.4× the *5-minute* ATR, the designed loss per position is roughly
**0.5–1% of CAPITAL** (use ~1% as a safe planning figure). Portfolio designed loss ≈
that fraction of total deployed capital.

> ⚠️ This assumes stops fill at their trigger. If a stop is rejected, unfilled on a
> gap, or the stock hits a circuit, a position's loss is bounded instead by its
> **notional (~CAPITAL)** — much larger. Size against total notional exposure, not
> the designed loss, and treat any "UNPROTECTED" log line as a signal to flatten
> manually.

## Order reliability & safeguards

Live order placement on Dhan has several gotchas the bot now handles:

- **IP whitelist (`DH-905 Invalid IP`)** — Dhan only accepts orders from a whitelisted
  public IP. Whitelist this machine's **public IPv4** in your DhanHQ API settings.
  After changing it you may need a **fresh token** (delete `.token_cache`) for the
  change to take effect. The startup preflight catches this before trading.
- **Stop-loss price rules (`DH-906`)** — a stop order's limit price must differ from
  its trigger; SL-Market is not accepted. The bot places a stop-**limit** with the
  limit offset from the trigger in the fill direction.
- **Tick size (`EXCH:16283`)** — order prices must be a multiple of the instrument's
  tick (read from the scrip master; ₹0.05/₹0.10/₹0.50 depending on price). The bot
  rounds every trigger and limit to the correct tick.
- **Submission ≠ acceptance** — Dhan returns `success` on submission, but the exchange
  can reject milliseconds later. The bot polls order status after placing and logs
  `Position is UNPROTECTED — exit manually!` if a stop is rejected post-submission.

If you ever see an `UNPROTECTED` warning, exit that position manually — the bot will
otherwise leave it open until the 3:15 PM square-off.

## Tests

```bash
pytest tests/ -v --cov=src
```

105 tests covering indicators, orders (placement, stop-loss tick rounding, status
confirmation), signal logic, data utilities, tick size, square-off timing, and
candlestick patterns.

## Requirements

- Python 3.8+
- Dhan trading account with API access enabled

## Disclaimer

This software is for educational purposes only. Algorithmic trading carries significant financial risk. Always test thoroughly with `--dry-run` before using real capital.
