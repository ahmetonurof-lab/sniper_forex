#!/usr/bin/env python
"""Sniper Forex - Main Module - Phase 1"""

import sys
import os
import importlib.util


def get_project_root():
    """Get the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dependencies():
    """Test that required dependencies are available."""
    print("Testing dependencies...")
    if importlib.util.find_spec("MetaTrader5") is not None:
        print("  ✓ MetaTrader5 available")
        return True
    else:
        print("  ✗ MetaTrader5 not available")
        return False


def main():
    """Main entry point for Phase 0/bootstrap testing."""
    print("Sniper Forex - Phase 0: Project Bootstrap & Architecture Test")
    print("=" * 60)

    # Check dependencies
    if not test_dependencies():
        print("\nDependency check failed. Exiting.")
        sys.exit(1)

    # Run architecture test
    from src.test_mt5_connection import test_architecture

    success = test_architecture()

    if success:
        print("\n✓ Phase 0 architecture validation passed!")
        print("- No orders were sent")
        print("- No strategy was implemented")
        print("- No trading logic active")
        print("- Architecture verified: config → data/trading → strategy → main")
    else:
        print("\n✗ Architecture validation failed. Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
