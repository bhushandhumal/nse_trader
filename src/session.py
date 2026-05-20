import os
from dotenv import load_dotenv
from dhanhq import dhanhq

# TODO (multi-broker): replace this module with a broker_factory.py that reads
# BROKER=zerodha|dhan|both from .env and returns a BaseBroker-compatible instance.

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')


def load_session():
    """Returns a DhanHQ client using credentials from .env.

    Dhan access tokens are long-lived (~30 days) — no daily Selenium login needed.
    Regenerate the token from https://api.dhan.co when it expires.
    """
    load_dotenv(ENV_FILE)
    return dhanhq(os.environ['DHAN_CLIENT_ID'], os.environ['DHAN_ACCESS_TOKEN'])
