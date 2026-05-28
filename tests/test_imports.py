"""Basic import checks for hyperliquid_autopilot."""
import importlib
import sys

import pytest


def test_import_common():
    mod = importlib.import_module("hyperliquid_autopilot.common")
    assert hasattr(mod, "make_info_client")
    assert hasattr(mod, "make_exchange_client")
    assert hasattr(mod, "get_base_url")
    assert hasattr(mod, "is_testnet")
    assert hasattr(mod, "parse_decimal")
    assert hasattr(mod, "decimal_to_text")


def test_import_quote():
    mod = importlib.import_module("hyperliquid_autopilot.quote")
    assert hasattr(mod, "get_mid_price")
    assert hasattr(mod, "prepare_quote")
    assert hasattr(mod, "summarize_quote")


def test_import_order():
    mod = importlib.import_module("hyperliquid_autopilot.order")
    assert hasattr(mod, "place_market_order")
    assert hasattr(mod, "place_limit_order")
    assert hasattr(mod, "cancel_order")
    assert hasattr(mod, "set_leverage")
    assert hasattr(mod, "close_position")
    assert hasattr(mod, "get_positions")


def test_import_flow():
    mod = importlib.import_module("hyperliquid_autopilot.flow")
    assert hasattr(mod, "run_trade_flow")


def test_version():
    import hyperliquid_autopilot
    import re
    assert re.match(r"^\d+\.\d+\.\d+", hyperliquid_autopilot.__version__)
