"""Quick connectivity check — run anytime to verify Dhan session and API access.

Usage: python check_connection.py --env=dev|uat|prod
"""
import sys
from dotenv import load_dotenv
from src.session import load_session
from src.data import get_instruments, fetch_ltp

_env_arg = next((a.split('=')[1] for a in sys.argv if a.startswith('--env=')), None)
if _env_arg not in ('dev', 'uat', 'prod'):
    print("Usage: python check_connection.py --env=dev|uat|prod")
    sys.exit(1)

load_dotenv(f'.env.{_env_arg}', override=True)
dhan = load_session()

# 1. Auth check — fund limits work outside market hours
print(f"\n[env={_env_arg}] --- Fund Limits ---")
resp = dhan.get_fund_limits()
if resp.get('status') == 'success':
    data = resp.get('data', {})
    print(f"  Available cash : {data.get('availabelBalance', 'N/A')}")
    print(f"  Used margin    : {data.get('utilizedAmount', 'N/A')}")
else:
    print(f"  FAILED: {resp}")

# 2. Instruments download
print("\n--- Scrip Master ---")
df = get_instruments()
print(f"  Records loaded : {len(df)}")

# 3. LTP for one ticker (only meaningful during market hours)
print("\n--- LTP (RELIANCE) ---")
ltp = fetch_ltp(dhan, df, 'RELIANCE')
print(f"  LTP : {ltp if ltp else 'N/A (market may be closed)'}")
