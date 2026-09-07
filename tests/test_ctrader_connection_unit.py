#!/usr/bin/env python
"""Unit tests for cTrader Open API connection layer — D126 Adım A.2.

These tests exercise the REAL production code path in
src/ctrader/connection.py WITHOUT establishing a network socket —
they validate config parsing, token-cache round-tripping, heartbeat
throttling, and protobuf message construction (via the real SDK).

They deliberately do NOT spin up the Twisted reactor or connect to
demo.ctraderapi.com (that requires KYC-approved credentials and lives
in the integration/manual phase). See AGENTS.md §3 evidence hierarchy:
these are controlled-unit-evidence, not production-network-proof.
"""

import json
import time

import pytest

from src.config.ctrader_config import (
    get_ctrader_config,
    validate_ctrader_config,
)
from src.ctrader.connection import (
    HEARTBEAT_INTERVAL_SEC,
    CTraderConnection,
)

# Minimal structurally-valid config (credential-free — KYC pendig)
DEMO_CONFIG = {
    "client_id": "",
    "client_secret": "",
    "host": "demo.ctraderapi.com",
    # Placeholder (D126): 10103194 is a traderLogin, NOT a ctidTraderAccountId
    # (D142). Real id lives in .env as a deployment value.
    "account_id": "10103194",
    "redirect_uri": "http://localhost",
}


def _make_conn(tmp_path, config=None, token_json=None):
    """Construct a CTraderConnection with a throwaway token cache."""
    tok_path = tmp_path / "token_cache.json"
    if token_json is not None:
        tok_path.write_text(json.dumps(token_json), encoding="utf-8")
    conn = CTraderConnection(config or dict(DEMO_CONFIG), token_cache_path=str(tok_path))
    return conn, tok_path


# ---------------------------------------------------------------- config
def test_config_loads_from_real_env_without_hanging_on_empty_fields():
    """Real .env drives defaults; absent creds stay '' (structural validity)."""
    cfg = get_ctrader_config()
    assert cfg["host"] == "demo.ctraderapi.com"
    # D142: .env account_id is a deployment value (server-verified demo
    # ctidTraderAccountId), not a frozen constant — assert wiring + shape.
    assert cfg["account_id"].isdigit()


def test_structurally_valid_without_creds():
    """Credential-less config validates structurally (needed pre-KYC)."""
    cfg = validate_ctrader_config(dict(DEMO_CONFIG), require_credentials=False)
    assert cfg["account_id"] == "10103194"


def test_strict_validation_requires_client_id():
    """With require_credentials=True, missing client_id raises."""
    with pytest.raises(ValueError, match="CLIENT_ID"):
        validate_ctrader_config(dict(DEMO_CONFIG), require_credentials=True)


def test_host_is_nonnegotiable():
    bad = dict(DEMO_CONFIG)
    bad["host"] = ""  # simulate unset CTRADER_HOST
    with pytest.raises(ValueError, match="HOST"):
        validate_ctrader_config(bad, require_credentials=False)


# ------------------------------------------------------------ token cache
def test_token_cache_template_initially_null(tmp_path):
    conn, _ = _make_conn(tmp_path)
    assert conn.token_cache == {
        "access_token": None,
        "refresh_token": None,
        "expires_at": None,
    }


def test_token_cache_roundtrips_to_disk(tmp_path):
    conn, tok_path = _make_conn(tmp_path)
    conn.token_cache["access_token"] = "abc123"
    conn.save_token_cache()
    reread = json.loads(tok_path.read_text(encoding="utf-8"))
    assert reread["access_token"] == "abc123"


def test_token_cache_loads_prepopulated(tmp_path):
    conn, _ = _make_conn(
        tmp_path, token_json={"access_token": "tok", "refresh_token": "rf", "expires_at": 999}
    )
    assert conn.token_cache["access_token"] == "tok"
    assert conn.token_cache["refresh_token"] == "rf"


# ------------------------------------------------------------- heartbeat
def test_heartbeat_throttles_by_interval(tmp_path):
    """First beat sends; immediate second is throttled (< interval elapsed)."""
    conn, _ = _make_conn(tmp_path)
    conn._last_heartbeat_sent = 0.0
    conn.send_heartbeat()  # fires -> timestamp advances
    ts_first = conn._last_heartbeat_sent
    assert ts_first > 0.0
    conn.send_heartbeat()  # instantly -> suppressed
    assert conn._last_heartbeat_sent == ts_first


def test_heartbeat_allows_next_after_interval(tmp_path):
    conn, _ = _make_conn(tmp_path)
    conn._last_heartbeat_sent = time.time() - HEARTBEAT_INTERVAL_SEC - 1.0
    conn.send_heartbeat()
    assert conn._last_heartbeat_sent > time.time() - 1.0


# ------------------------------------------- protobuf message construction
def test_application_auth_msg_populates_ids(tmp_path):
    """Real SDK builds ProtoOAApplicationAuthReq with supplied creds."""
    from ctrader_open_api.protobuf import Protobuf

    cfg = dict(DEMO_CONFIG)
    cfg["client_id"] = "cid"
    cfg["client_secret"] = "sec"
    conn, _ = _make_conn(tmp_path, config=cfg)
    req = Protobuf.get("ProtoOAApplicationAuthReq")
    req.clientId = conn.config["client_id"]
    req.clientSecret = conn.config["client_secret"]
    serialized = req.SerializeToString()
    parsed = Protobuf.get("ProtoOAApplicationAuthReq")
    parsed.ParseFromString(serialized)
    assert parsed.clientId == "cid"
    assert parsed.clientSecret == "sec"


def test_account_auth_msg_targets_int_account_id(tmp_path):
    """Real SDK stores the numeric-string account id as int64."""
    from ctrader_open_api.protobuf import Protobuf

    conn, _ = _make_conn(tmp_path)
    req = Protobuf.get("ProtoOAAccountAuthReq")
    req.ctidTraderAccountId = int(conn.config["account_id"])  # mirrors production coercion
    req.accessToken = "accTok"
    parsed = Protobuf.get("ProtoOAAccountAuthReq")
    parsed.ParseFromString(req.SerializeToString())
    assert parsed.ctidTraderAccountId == int(DEMO_CONFIG["account_id"])
    assert parsed.accessToken == "accTok"


def test_symbols_list_msg_settable(tmp_path):
    """ProtoOASymbolsListReq accepts account id + archived toggle."""
    from ctrader_open_api.protobuf import Protobuf

    conn, _ = _make_conn(tmp_path)
    req = Protobuf.get("ProtoOASymbolsListReq")
    req.ctidTraderAccountId = int(conn.config["account_id"])
    req.includeArchivedSymbols = False
    parsed = Protobuf.get("ProtoOASymbolsListReq")
    parsed.ParseFromString(req.SerializeToString())
    assert parsed.includeArchivedSymbols is False
