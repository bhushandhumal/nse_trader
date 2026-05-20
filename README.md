# nse_trader

An intraday trading bot for NSE (India) built on [Zerodha KiteConnect](https://kite.trade/docs/connect/v3/).

## Features

- **Auto-login** — headless Selenium + TOTP, stores access token in `.env`
- **Three Supertrends strategy** — ATR-based trend confirmation across three parameter sets
- **SMA Crossover strategy** — fast/slow moving average crossover signals
- **Candlestick pattern scanner** — doji, hammer, shooting star, marubozu, harami cross, engulfing
- **Pivot point support/resistance** — floor pivot levels for significance detection
- **Market hours guard** — runs only during NSE session (Mon–Fri, 9:15–15:30)

## Project Structure

```
nse_trader/
├── .env.example              # credential template — copy to .env and fill in
├── requirements.txt
├── main.py                   # entry point
└── src/
    ├── session.py            # auto_login, load_session
    ├── data.py               # fetch_ohlc, fetch_ltp, instrument_lookup
    ├── indicators.py         # atr, supertrend, sma_crossover_signal, sl_price
    ├── candlesticks.py       # pattern detection + pivot levels
    ├── orders.py             # place_sl_order, modify_sl_order
    └── strategies/
        ├── sma_crossover.py
        └── three_supertrends.py
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

Edit `.env` with your Zerodha credentials:

```
APP_KEY=your_zerodha_api_key
SECRET_KEY=your_zerodha_api_secret
USERNAME=your_zerodha_user_id
PASSWORD=your_zerodha_password
TOTP=your_totp_secret_base32
```

> **Note:** `.env` is gitignored and will never be committed.

### 3. KiteConnect app setup

1. Create an app at [kite.trade/developers](https://developers.kite.trade/)
2. Set the redirect URL to `http://127.0.0.1`
3. Copy the API key and secret into `.env`

### 4. Run

```bash
python main.py
```

On startup it will auto-login via Selenium (headless Chrome), fetch instruments once, then run the three-supertrend strategy every 5 minutes during market hours.

## Configuration

Edit the top of `main.py` to change tickers, capital per trade, or run duration:

```python
TICKERS = ["GODREJCP", "DABUR", "ICICIPRULI", "NAUKRI", "HAVELLS", "INDHOTEL"]
CAPITAL = 3000            # max capital per position (INR)
RUN_DURATION_HOURS = 6
INTERVAL_SECONDS = 300    # scan every 5 minutes
```

## Strategies

### Three Supertrends (`src/strategies/three_supertrends.py`)

Places an intraday MIS entry + stop-loss order when all three supertrend indicators align (all green = buy, all red = sell). Modifies the SL order on each subsequent tick.

| Parameter | ST1 | ST2 | ST3 |
|-----------|-----|-----|-----|
| ATR period | 7 | 10 | 11 |
| Multiplier | 3 | 3 | 2 |

### SMA Crossover (`src/strategies/sma_crossover.py`)

Prints buy/sell alerts when the 5-period MA crosses the 15-period MA. No order placement — use as a screener.

## Requirements

- Python 3.8+
- Google Chrome + ChromeDriver (matching versions)
- Zerodha account with KiteConnect API subscription

## Disclaimer

This software is for educational purposes only. Algorithmic trading carries significant financial risk. Always test thoroughly in paper trading mode before using real capital.
