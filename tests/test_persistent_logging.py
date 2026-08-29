#!/usr/bin/env python
"""Tests for persistent logging and AuditChain auto-flush."""

import json
import logging
import os
import sys
import tempfile
import time

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.audit import AuditChain, EventType
from src.live.persistent_log import setup_logging, _mask_sensitive, LOGGER_NAME


def _reset_logger():
    """Clear all handlers from the singleton logger for test isolation."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)


def test_logger_creates_file():
    """Logger creates a log file on disk."""
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs")
        logger = setup_logging(log_dir=log_dir, level=logging.DEBUG)
        logger.info("test message")

        # Flush and close handlers before cleanup
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        log_file = os.path.join(log_dir, "sniper_forex.log")
        assert os.path.exists(log_file), f"Log file not created: {log_file}"

        with open(log_file, "r") as f:
            content = f.read()
            assert "test message" in content
    _reset_logger()
    print("PASS: test_logger_creates_file")


def test_log_survives_process_lifetime():
    """Log file persists after logger goes out of scope."""
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs")
        logger = setup_logging(log_dir=log_dir)
        logger.info("persistent message")

        # Flush before "restart"
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        # Simulate process restart by resetting and creating new logger
        _reset_logger()
        logger2 = setup_logging(log_dir=log_dir)
        logger2.info("after restart")

        # Flush before reading
        for handler in logger2.handlers:
            handler.flush()
            handler.close()

        log_file = os.path.join(log_dir, "sniper_forex.log")
        with open(log_file, "r") as f:
            content = f.read()
            assert "persistent message" in content
            assert "after restart" in content
    _reset_logger()
    print("PASS: test_log_survives_process_lifetime")


def test_rotation_works():
    """Log rotation creates backup files."""
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs")
        # Small max bytes to trigger rotation quickly
        logger = setup_logging(log_dir=log_dir, max_bytes=500, backup_count=3)

        # Write enough to trigger rotation
        for i in range(20):
            logger.info(f"Rotation test message {i} with padding to exceed limit")

        # Flush and close before checking
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        log_file = os.path.join(log_dir, "sniper_forex.log")
        assert os.path.exists(log_file)

        # Check for rotated files
        rotated = [f for f in os.listdir(log_dir) if f.startswith("sniper_forex.log.")]
        assert len(rotated) > 0, "No rotated files created"
    _reset_logger()
    print("PASS: test_rotation_works")


def test_sensitive_values_masked():
    """Sensitive values are masked in log output."""
    _reset_logger()
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs")
        logger = setup_logging(log_dir=log_dir)

        # These should be masked
        logger.info("password=secret123")
        logger.info("MT5_PASSWORD=mysecret")
        logger.info("api_key=abc123")

        # Flush before reading
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        log_file = os.path.join(log_dir, "sniper_forex.log")
        with open(log_file, "r") as f:
            content = f.read()
            assert "secret123" not in content, "Password not masked"
            assert "mysecret" not in content, "MT5_PASSWORD not masked"
            assert "abc123" not in content, "API key not masked"
            assert "***" in content, "Mask indicator not present"
    _reset_logger()
    print("PASS: test_sensitive_values_masked")


def test_audit_chain_flush_creates_valid_jsonl():
    """AuditChain flush creates valid JSONL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = os.path.join(tmpdir, "audit.jsonl")
        audit = AuditChain(auto_flush_path=audit_path, flush_threshold=5)

        for i in range(10):
            audit.append(time.time(), EventType.SIGNAL, "EURUSD", {"index": i})

        assert os.path.exists(audit_path), "Audit file not created"

        with open(audit_path, "r") as f:
            lines = f.readlines()
            assert len(lines) >= 5, f"Expected at least 5 lines, got {len(lines)}"

            for line in lines:
                obj = json.loads(line)
                assert "timestamp" in obj
                assert "event_type" in obj
                assert obj["event_type"] == "SIGNAL"
    print("PASS: test_audit_chain_flush_creates_valid_jsonl")


def test_audit_chain_shutdown_flush():
    """AuditChain.shutdown() performs final flush."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = os.path.join(tmpdir, "audit.jsonl")
        audit = AuditChain(
            auto_flush_path=audit_path, flush_threshold=100
        )  # High threshold

        for i in range(10):
            audit.append(time.time(), EventType.ORDER, "GBPUSD", {"index": i})

        # File shouldn't exist yet (threshold not met)
        assert not os.path.exists(audit_path), "File created before shutdown"

        # Shutdown should flush
        audit.shutdown()

        assert os.path.exists(audit_path), "File not created after shutdown"

        with open(audit_path, "r") as f:
            lines = f.readlines()
            assert len(lines) == 10, f"Expected 10 lines, got {len(lines)}"
    print("PASS: test_audit_chain_shutdown_flush")


def test_audit_chain_auto_flush_on_threshold():
    """AuditChain auto-flushes when event threshold is reached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = os.path.join(tmpdir, "audit.jsonl")
        audit = AuditChain(
            auto_flush_path=audit_path, flush_threshold=5, flush_interval_sec=60
        )

        for i in range(12):
            audit.append(time.time(), EventType.CANDLE, "EURUSD", {"index": i})
            if i == 4:
                # After 5 events, file should exist
                assert os.path.exists(audit_path), (
                    "Auto-flush didn't trigger at threshold"
                )

        with open(audit_path, "r") as f:
            lines = f.readlines()
            assert len(lines) >= 5, f"Expected at least 5 lines, got {len(lines)}"
    print("PASS: test_audit_chain_auto_flush_on_threshold")


def test_audit_chain_auto_flush_on_interval():
    """AuditChain auto-flushes when time interval is reached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = os.path.join(tmpdir, "audit.jsonl")
        audit = AuditChain(
            auto_flush_path=audit_path, flush_threshold=100, flush_interval_sec=1
        )

        audit.append(time.time(), EventType.SIGNAL, "EURUSD", {"index": 0})
        time.sleep(1.5)  # Wait for interval
        audit.append(time.time(), EventType.SIGNAL, "EURUSD", {"index": 1})

        assert os.path.exists(audit_path), "Auto-flush didn't trigger on interval"
    print("PASS: test_audit_chain_auto_flush_on_interval")


def test_mask_sensitive_function():
    """_mask_sensitive masks various patterns."""
    assert "***" in _mask_sensitive("password=secret")
    assert "***" in _mask_sensitive("MT5_PASSWORD=mysecret")
    assert "***" in _mask_sensitive("api_key=abc123")
    assert "***" in _mask_sensitive("token=xyz789")
    # Non-sensitive should pass through
    assert "hello world" in _mask_sensitive("hello world")
    print("PASS: test_mask_sensitive_function")


if __name__ == "__main__":
    test_logger_creates_file()
    test_log_survives_process_lifetime()
    test_rotation_works()
    test_sensitive_values_masked()
    test_audit_chain_flush_creates_valid_jsonl()
    test_audit_chain_shutdown_flush()
    test_audit_chain_auto_flush_on_threshold()
    test_audit_chain_auto_flush_on_interval()
    test_mask_sensitive_function()
    print("\nAll tests passed!")
