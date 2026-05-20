# nse_trader

An intraday trading bot for NSE (India) built on the [Dhan API](https://dhanhq.co/docs/v2/).

## Features

- **Simple auth** — Dhan access tokens are long-lived (~30 days), no daily Selenium login needed
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
    ├── session.py            # load_session (DhanHQ client)
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

Edit `.env` with your Dhan credentials:

```
DHAN_CLIENT_ID=your_dhan_client_id
DHAN_ACCESS_TOKEN=your_dhan_access_token
```

> **Note:** `.env` is gitignored and will never be committed.

### 3. Get Dhan API credentials

1. Log in to [api.dhan.co](https://api.dhan.co)
2. Create a new app and generate an access token
3. Copy the **Client ID** and **Access Token** into `.env`
4. Tokens are valid for ~30 days — regenerate from the same page when expired

### 4. Run

```bash
python main.py
```

On startup it downloads the Dhan scrip master (instrument list), then runs the three-supertrend strategy every 5 minutes during market hours.

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

Places an intraday INTRADAY entry + stop-loss order when all three supertrend indicators align (all green = buy, all red = sell). Modifies the SL order on each subsequent tick.

| Parameter  | ST1 | ST2 | ST3 |
|------------|-----|-----|-----|
| ATR period | 7   | 10  | 11  |
| Multiplier | 3   | 3   | 2   |

### SMA Crossover (`src/strategies/sma_crossover.py`)

Prints buy/sell alerts when the 5-period MA crosses the 15-period MA. No order placement — use as a screener.

## Requirements

- Python 3.8+
- Dhan trading account with API access enabled

## Disclaimer

This software is for educational purposes only. Algorithmic trading carries significant financial risk. Always test thoroughly in paper trading mode before using real capital.
