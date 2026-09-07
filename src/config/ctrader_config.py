#!/usr/bin/env python
"""cTrader Configuration Module — D126 Adım A.1

Reads cTrader Open API credentials from environment variables.
Follows the same pattern as src/config/mt5_config.py:
never hardcodes credentials in source code.
Loads .env file from project root reliably.
"""

import os
from pathlib import Path

# Resolve project root reliably: this file is at src/config/ctrader_config.py
# Project root is two levels up from this file
_PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load .env file from project root (outside source code)
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    # override=False so explicit env vars take priority
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def get_ctrader_config():
    """Get cTrader Open API configuration from environment variables.

    Returns dict with configuration values.
    Credentials are read from environment at runtime, never hardcoded.
    .env file is loaded from project root before reading env vars.
    """
    config = {
        # OAuth2 application credentials (KYC onayı sonrası doldurulur)
        "client_id": os.getenv("CTRADER_CLIENT_ID", ""),
        "client_secret": os.getenv("CTRADER_CLIENT_SECRET", ""),
        # Host: demo.ctraderapi.com | live.ctraderapi.com
        "host": os.getenv("CTRADER_HOST", "demo.ctraderapi.com"),
        # cTrader demo account (ctidTraderAccountId)
        "account_id": os.getenv("CTRADER_ACCOUNT_ID", ""),
        # OAuth2 redirect URI (onay sonrası kaydedilecek)
        "redirect_uri": os.getenv("CTRADER_REDIRECT_URI", "http://localhost"),
        # Access token (Adım A.3 — Reis iletimi D140). Optional: connection
        # also supports token_cache.json via the OAuth2 refresh flow.
        "access_token": os.getenv("CTRADER_ACCESS_TOKEN", ""),
    }
    return config


def validate_ctrader_config(config, require_credentials=True):
    """Validate cTrader configuration.

    require_credentials=True → client_id/client_secret must be non-empty
    (KYC onayı sonrası). When False, only structural fields are validated
    so connection-skeleton tests can run before credentials arrive.
    """
    if not config["host"]:
        raise ValueError("CTRADER_HOST environment variable not set")
    if not config["account_id"]:
        raise ValueError("CTRADER_ACCOUNT_ID environment variable not set")
    if require_credentials:
        if not config["client_id"]:
            raise ValueError("CTRADER_CLIENT_ID environment variable not set")
        if not config["client_secret"]:
            raise ValueError("CTRADER_CLIENT_SECRET environment variable not set")
    return config
