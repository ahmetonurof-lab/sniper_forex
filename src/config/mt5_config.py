#!/usr/bin/env python
"""MT5 Configuration Module - Phase 0

Reads MT5 connection credentials from environment variables.
Never hardcodes credentials in source code.
Loads .env file from project root reliably.
"""

import os
from pathlib import Path

# Resolve project root reliably: this file is at src/config/mt5_config.py
# Project root is two levels up from this file
_PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load .env file from project root (outside source code)
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    # python-dotenv will read and set environment variables
    # we use override=False so explicit env vars take priority
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def get_mt5_config():
    """Get MT5 configuration from environment variables.

    Returns dict with configuration values.
    Credentials are read from environment at runtime, never hardcoded.
    .env file is loaded from project root before reading env vars.
    """
    config = {
        # Server name - can be set as default here but read from env at runtime
        "server": os.getenv("MT5_SERVER", ""),
        # Login - required environment variable
        "login": os.getenv("MT5_LOGIN", ""),
        # Password - required environment variable
        "password": os.getenv("MT5_PASSWORD", ""),
        # Terminal path - optional, can be set at runtime
        "terminal_path": os.getenv("MT5_TERMINAL_PATH", ""),
    }

    # Validate required credentials
    if not config["login"]:
        raise ValueError("MT5_LOGIN environment variable not set")
    if not config["password"]:
        raise ValueError("MT5_PASSWORD environment variable not set")
    if not config["server"]:
        raise ValueError("MT5_SERVER environment variable not set")

    return config


def get_default_server():
    """Get default MT5 server name (informational, not for security)."""
    # This is just a placeholder - actual server should come from env
    return os.getenv("MT5_SERVER", "ICMarketsSC-Demo")


def mask_sensitive_info(config_dict):
    """Mask sensitive information for logging/display."""
    masked = dict(config_dict)
    if "password" in masked:
        masked["password"] = "••••••••"
    return masked
