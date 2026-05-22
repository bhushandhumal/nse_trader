# nse_trader

An intraday trading bot for NSE (India) built on the [Dhan API](https://dhanhq.co/docs/v2/).

## Features

- **TOTP-based auth** — auto-generates a fresh Dhan access token on startup using PIN + TOTP; no manual token rotation needed
- **Three Supertrends strategy** — ATR-based trend confirmation across three parameter sets
- **Pre-market screener** — scans Nifty 200 each morning, ranks by ADX and ATR%, outputs a ready-to-paste `TICKERS=` line
- **SMA Crossover strategy** — fast/slow moving average crossover signals
- **Candlestick pattern scanner** — doji, hammer, shooting star, marubozu
- **Pivot point support/resistance** — floor pivot levels
- **Market hours guard** — runs only during NSE session (Mon–Fri, 9:15–15:30)
- **Square-off** — closes all positions at 3:15 PM before Dhan's auto square-off

## Project Structure

```
nse_trader/
├── .env.example                          # credential template — copy to .env and fill in
├── .env                                  # your credentials (gitignored)
├── requirements.txt
├── main.py                               # entry point
├── check_connection.py                   # verify Dhan session and API access
└── src/
    ├── session.py                        # TOTP login, token caching
    ├── data.py                           # fetch_ohlc, fetch_ltp, instrument_lookup
    ├── indicators.py                     # atr, supertrend, sl_price
    ├── candlesticks.py                   # pattern detection + pivot levels
    ├── orders.py                         # place_sl_order, modify_sl_order, square_off_all
    └── strategies/
        ├── three_supertrends.py          # main intraday strategy
        ├── three_supertrends_screener.py # pre-market Nifty 200 screener
        └── sma_crossover.py
```

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/bhushandhumal/nse_trader.git
cd nse_trader
pip install -r requirements.txt
```

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

The bot runs every 5 minutes, places SL orders on supertrend signals, and squares off all positions at 3:15 PM.

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

## Tests

```bash
pytest tests/ -v --cov=src
```

87 tests covering indicators, orders, signal logic, data utilities, and candlestick patterns.

## Requirements

- Python 3.8+
- Dhan trading account with API access enabled

## Disclaimer

This software is for educational purposes only. Algorithmic trading carries significant financial risk. Always test thoroughly with `--dry-run` before using real capital.
