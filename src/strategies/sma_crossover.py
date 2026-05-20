from src.indicators import sma_crossover_signal
from src.data import fetch_ohlc

FAST_MA = 5
SLOW_MA = 15


def run(kite, instrument_df, tickers, interval='day', duration=60):
    """Scans tickers for SMA crossover signals and prints buy/sell alerts."""
    for ticker in tickers:
        try:
            ohlc = fetch_ohlc(kite, instrument_df, ticker, interval, duration)
            signal = sma_crossover_signal(ohlc, fast=FAST_MA, slow=SLOW_MA)
            if signal == 1:
                print(f"BUY  {ticker} — fast MA crossed above slow MA")
            elif signal == -1:
                print(f"SELL {ticker} — fast MA crossed below slow MA")
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
