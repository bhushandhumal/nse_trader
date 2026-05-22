"""Quick connectivity check — run anytime to verify Dhan session and API access.

Usage: python check_connection.py
"""
from dotenv import load_dotenv
from src.session import load_session
from src.data import get_instruments, fetch_ltp

load_dotenv('.env', override=True)
dhan = load_session()

# 1. Auth check — fund limits work outside market hours
print("\n--- Fund Limits ---")
resp = dhan.get_fund_limits()
if resp.get('status') == 'success':
    data = resp.get('data', {})
    print(f"  Available cash : {data.get('availabelBalance', 'N/A')}")
    print(f"  Used margin    : {data.get('utilizedAmount', 'N/A')}")
else:
    print(f"  FAILED: {resp}")
    raise SystemExit(1)

# 2. LTP for one ticker (only meaningful during market hours)
print("\n--- LTP (RELIANCE) ---")
df = get_instruments()
ltp = fetch_ltp(dhan, df, 'RELIANCE')
print(f"  LTP : {ltp if ltp else 'N/A (market may be closed)'}")
