import os
import json
import time
import base64
import logging
import pyotp
from dotenv import load_dotenv
from dhanhq import dhanhq, DhanContext
from dhanhq.auth import DhanLogin

ENV_FILE   = os.path.join(os.path.dirname(__file__), '..', '.env')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', '.token_cache')

# Regenerate token this many seconds before it actually expires (1 hour buffer)
_EXPIRY_BUFFER = 3600


def _jwt_exp(token):
    """Decode JWT exp field without verification."""
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return int(data.get('exp', 0))
    except Exception:
        return 0


def _load_cached_token():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        token = data.get('access_token', '')
        exp   = _jwt_exp(token)
        if exp > time.time() + _EXPIRY_BUFFER:
            return token
    except Exception:
        pass
    return None


def _save_token(token):
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump({'access_token': token}, f)
    except Exception as e:
        logging.warning(f"Could not save token cache: {e}")


def load_session():
    """Returns a DhanHQ client.

    Reuses the cached access token if still valid (tokens last ~30 days).
    Generates a fresh token via TOTP only when the cached one is missing or
    about to expire.
    """
    load_dotenv(ENV_FILE)
    client_id = os.environ['DHAN_CLIENT_ID']

    token = _load_cached_token()
    if token:
        logging.info("Reusing cached access token.")
    else:
        totp_secret = os.environ['DHAN_TOTP_SECRET'].strip()
        pin         = os.environ['DHAN_PIN'].strip()
        totp        = pyotp.TOTP(totp_secret).now()
        logging.info("Generating fresh access token via TOTP...")
        result = DhanLogin(client_id).generate_token(pin, totp)
        token  = result.get('accessToken') or result.get('access_token')
        if not token:
            raise RuntimeError(f"TOTP login failed — unexpected response: {result}")
        _save_token(token)
        logging.info("TOTP login successful, token cached.")

    ctx = DhanContext(client_id, token)
    return dhanhq(ctx)
