"""Logic tests for hyperliquid_autopilot."""
import os
import unittest
from decimal import Decimal
from unittest import mock

import pytest

from hyperliquid_autopilot.common import parse_decimal
from hyperliquid_autopilot.quote import prepare_quote
from hyperliquid_autopilot.order import place_market_order, close_position
from hyperliquid_autopilot.flow import run_trade_flow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_info_client(all_mids=None, l2_snapshot=None, user_state=None, open_orders=None):
    """Build a mock Hyperliquid Info client."""
    info = mock.MagicMock()
    info.all_mids.return_value = all_mids or {"ETH": "3000.5"}
    info.l2_snapshot.return_value = l2_snapshot or {
        "levels": [
            [{"px": "3000.0", "sz": "10"}, {"px": "2999.0", "sz": "5"}],   # bids
            [{"px": "3001.0", "sz": "8"}, {"px": "3002.0", "sz": "3"}],    # asks
        ]
    }
    info.user_state.return_value = user_state or {"assetPositions": [], "marginSummary": {}}
    info.open_orders.return_value = open_orders or []
    return info


def _mock_exchange_client(order_result=None, cancel_result=None, leverage_result=None):
    """Build a mock Hyperliquid Exchange client."""
    exchange = mock.MagicMock()
    exchange.order.return_value = order_result or {"status": "ok", "response": {}}
    exchange.cancel.return_value = cancel_result or "Success"
    exchange.bulk_cancel.return_value = cancel_result or [{"status": "ok"}]
    exchange.leverage_update.return_value = leverage_result or "Success"
    return exchange


# ---------------------------------------------------------------------------
# quote.py tests
# ---------------------------------------------------------------------------

class TestQuote(unittest.TestCase):

    def test_prepare_quote_buy(self):
        """Buy $100 of ETH — verifies slippage calculation."""
        info = _mock_info_client()
        with mock.patch("hyperliquid_autopilot.quote.make_info_client", return_value=info):
            result = prepare_quote(coin="ETH", is_buy=True, size_usd=100)

        self.assertEqual(result["coin"], "ETH")
        self.assertEqual(result["side"], "buy")
        self.assertIn("estimated_fill_price", result)
        self.assertIn("slippage_bps", result)
        # mid=3000.5, worst ask fills → slippage > 0
        self.assertTrue(Decimal(result["slippage_bps"]) >= 0)

    def test_prepare_quote_unknown_coin(self):
        """Querying unknown coin raises ValueError."""
        info = _mock_info_client(all_mids={"BTC": "60000"})
        with mock.patch("hyperliquid_autopilot.quote.make_info_client", return_value=info):
            with self.assertRaises(ValueError):
                prepare_quote(coin="ETH", is_buy=True, size_usd=100)


# ---------------------------------------------------------------------------
# order.py tests
# ---------------------------------------------------------------------------

class TestOrder(unittest.TestCase):

    def setUp(self):
        os.environ["HYPERLIQUID_WALLET_ADDRESS"] = "0x1234567890abcdef1234567890abcdef12345678"
        os.environ["HYPERLIQUID_PRIVATE_KEY"] = "0xabc123"

    def tearDown(self):
        for k in ("HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def test_market_order_limit_price(self):
        """Market buy at mid × (1+slippage)."""
        info = _mock_info_client()
        exchange = _mock_exchange_client()

        with mock.patch("hyperliquid_autopilot.order.make_info_client", return_value=info):
            with mock.patch("hyperliquid_autopilot.order.make_exchange_client", return_value=exchange):
                result = place_market_order(coin="ETH", is_buy=True, size=1.0, slippage=0.01)

        self.assertEqual(result["status"], "ok")
        exchange.order.assert_called_once()
        call_kwargs = exchange.order.call_args.kwargs
        # limit_px should be mid × 1.01 = 3000.5 × 1.01 ≈ 3030.505
        self.assertAlmostEqual(call_kwargs["limit_px"], 3000.5 * 1.01, places=2)

    def test_close_position_reverse_direction(self):
        """Short position → close = buy; long → close = sell."""
        pos_data = {
            "assetPositions": [{
                "position": {"coin": "ETH", "szi": "-1.5", "entryPx": "3000", "unrealizedPnl": "0", "marginUsed": "500"},
                "leverage": {"value": 5},
            }]
        }
        info = _mock_info_client(user_state=pos_data)
        exchange = _mock_exchange_client()

        with mock.patch("hyperliquid_autopilot.order.make_info_client", return_value=info):
            with mock.patch("hyperliquid_autopilot.order.make_exchange_client", return_value=exchange):
                result = close_position(coin="ETH")

        self.assertEqual(result["status"], "ok")
        # Short of -1.5 → close = buy (is_buy=True), size = 1.5
        call_kwargs = exchange.order.call_args.kwargs
        self.assertTrue(call_kwargs["is_buy"])
        self.assertAlmostEqual(call_kwargs["sz"], 1.5)


# ---------------------------------------------------------------------------
# flow.py tests
# ---------------------------------------------------------------------------

class TestFlow(unittest.TestCase):

    def setUp(self):
        # Set environment for wallet resolution
        os.environ["HYPERLIQUID_WALLET_ADDRESS"] = "0x1234567890abcdef1234567890abcdef12345678"
        os.environ["HYPERLIQUID_PRIVATE_KEY"] = "0xabc123"

    def tearDown(self):
        for k in ("HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def test_dry_run_no_order(self):
        """Dry-run returns quote without placing order."""
        info = _mock_info_client()
        exchange = _mock_exchange_client()

        with mock.patch("hyperliquid_autopilot.flow.make_info_client", return_value=info):
            with mock.patch("hyperliquid_autopilot.flow.make_exchange_client", return_value=exchange):
                result = run_trade_flow(coin="ETH", side="buy", size_usd=100, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["dry_run"], True)
        self.assertIn("quote", result)
        # Exchange should NOT be called
        exchange.order.assert_not_called()


# ---------------------------------------------------------------------------
# common.py tests
# ---------------------------------------------------------------------------

class TestCommon(unittest.TestCase):

    def test_parse_decimal_valid(self):
        self.assertEqual(parse_decimal("3.14"), Decimal("3.14"))
        self.assertEqual(parse_decimal(42), Decimal("42"))
        self.assertEqual(parse_decimal(Decimal("0.001")), Decimal("0.001"))

    def test_parse_decimal_invalid(self):
        with self.assertRaises(ValueError):
            parse_decimal("not_a_number", label="test_value")


class TestCommonRequireKey(unittest.TestCase):

    def setUp(self):
        os.environ.pop("HYPERLIQUID_PRIVATE_KEY", None)

    def test_require_private_key_from_env(self):
        from hyperliquid_autopilot.common import require_private_key
        os.environ["HYPERLIQUID_PRIVATE_KEY"] = "0xdeadbeef"
        try:
            self.assertEqual(require_private_key(), "0xdeadbeef")
        finally:
            os.environ.pop("HYPERLIQUID_PRIVATE_KEY", None)

    def test_require_private_key_auto_prefix(self):
        from hyperliquid_autopilot.common import require_private_key
        os.environ["HYPERLIQUID_PRIVATE_KEY"] = "abc123"
        try:
            self.assertEqual(require_private_key(), "0xabc123")
        finally:
            os.environ.pop("HYPERLIQUID_PRIVATE_KEY", None)

    def test_require_private_key_missing(self):
        from hyperliquid_autopilot.common import require_private_key
        with self.assertRaises(RuntimeError):
            require_private_key()


class TestCommonWallet(unittest.TestCase):

    def setUp(self):
        for k in ("HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_WALLET_ADDRESS_MAINNET",
                  "HYPERLIQUID_WALLET_ADDRESS_TESTNET", "HYPERLIQUID_TESTNET"):
            os.environ.pop(k, None)

    def test_wallet_address_mainnet_specific(self):
        from hyperliquid_autopilot.common import require_wallet_address
        os.environ["HYPERLIQUID_WALLET_ADDRESS_MAINNET"] = "0xAAA"
        try:
            self.assertEqual(require_wallet_address(), "0xAAA")
        finally:
            os.environ.pop("HYPERLIQUID_WALLET_ADDRESS_MAINNET", None)

    def test_wallet_address_fallback(self):
        from hyperliquid_autopilot.common import require_wallet_address
        os.environ["HYPERLIQUID_WALLET_ADDRESS"] = "0xBBB"
        try:
            self.assertEqual(require_wallet_address(), "0xBBB")
        finally:
            os.environ.pop("HYPERLIQUID_WALLET_ADDRESS", None)

    def test_wallet_address_missing(self):
        from hyperliquid_autopilot.common import require_wallet_address
        with self.assertRaises(RuntimeError):
            require_wallet_address()


class TestCommonNetwork(unittest.TestCase):

    def setUp(self):
        os.environ.pop("HYPERLIQUID_TESTNET", None)

    def test_mainnet_by_default(self):
        from hyperliquid_autopilot.common import get_base_url, MAINNET_URL, is_testnet
        self.assertEqual(get_base_url(), MAINNET_URL)
        self.assertFalse(is_testnet())

    def test_testnet_env(self):
        from hyperliquid_autopilot.common import get_base_url, TESTNET_URL, is_testnet
        os.environ["HYPERLIQUID_TESTNET"] = "1"
        try:
            self.assertEqual(get_base_url(), TESTNET_URL)
            self.assertTrue(is_testnet())
        finally:
            os.environ.pop("HYPERLIQUID_TESTNET", None)

    def test_testnet_env_yes(self):
        from hyperliquid_autopilot.common import is_testnet
        os.environ["HYPERLIQUID_TESTNET"] = "yes"
        try:
            self.assertTrue(is_testnet())
        finally:
            os.environ.pop("HYPERLIQUID_TESTNET", None)


class TestDecimalToText(unittest.TestCase):

    def test_integer(self):
        from hyperliquid_autopilot.common import decimal_to_text
        self.assertEqual(decimal_to_text(Decimal("42")), "42")

    def test_float(self):
        from hyperliquid_autopilot.common import decimal_to_text
        self.assertEqual(decimal_to_text(Decimal("3.14159")), "3.14159")
