#!/usr/bin/env python
"""D129 §3 — CBDR placeholder test.

Verifies get_cbdr_multiplier returns 1.0 and has correct docstring annotation.
"""

import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.risk import get_cbdr_multiplier


def test_placeholder_returns_one():
    """CBDR placeholder: her zaman 1.0 döner."""
    assert get_cbdr_multiplier("EURUSD", 0.15) == 1.0
    assert get_cbdr_multiplier("GBPUSD", 0.0) == 1.0
    assert get_cbdr_multiplier("USDJPY", 1.0) == 1.0


def test_docstring_has_ertelendi():
    """Docstring 'kalibrasyon ertelendi' ibaresini içerir."""
    assert "ertelendi" in get_cbdr_multiplier.__doc__.lower()


if __name__ == "__main__":
    test_placeholder_returns_one()
    print("PASS: test_placeholder_returns_one")
    test_docstring_has_ertelendi()
    print("PASS: test_docstring_has_ertelendi")
