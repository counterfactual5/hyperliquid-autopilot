"""Tests for hyperliquid-autopilot risk-control policy (shared + project-specific)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal

from hyperliquid_autopilot.policy import (
    Policy,
    check,
    check_hyperliquid,
    load_policy,
)


class TestSharedChecks(unittest.TestCase):
    """Shared policy rules work in hyperliquid context."""

    def test_max_amount_reject(self) -> None:
        pol = Policy(max_amount=Decimal("50"))
        result = check(pol, {"amount": "100"})
        self.assertFalse(result.allowed)

    def test_allowed_chains_reject(self) -> None:
        pol = Policy(allowed_chains=["hyperliquid"])
        result = check(pol, {"chain": "ethereum"})
        self.assertFalse(result.allowed)

    def test_blacklist_reject(self) -> None:
        pol = Policy(blacklist_addresses=["0xbad"])
        result = check(pol, {"sender": "0xBaD"})
        self.assertFalse(result.allowed)


class TestMaxLeverage(unittest.TestCase):
    """Hyperliquid-specific: max_leverage."""

    def test_under_limit(self) -> None:
        pol = Policy(extra={"max_leverage": 10})
        result = check_hyperliquid(pol, {"leverage": 5})
        self.assertTrue(result.allowed)

    def test_at_limit(self) -> None:
        pol = Policy(extra={"max_leverage": 10})
        result = check_hyperliquid(pol, {"leverage": 10})
        self.assertTrue(result.allowed)

    def test_over_limit(self) -> None:
        pol = Policy(extra={"max_leverage": 10})
        result = check_hyperliquid(pol, {"leverage": 20})
        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].rule, "max_leverage")

    def test_no_limit_set(self) -> None:
        pol = Policy()
        result = check_hyperliquid(pol, {"leverage": 100})
        self.assertTrue(result.allowed)


class TestAllowedCoins(unittest.TestCase):
    """Hyperliquid-specific: allowed_coins."""

    def test_allowed(self) -> None:
        pol = Policy(extra={"allowed_coins": ["ETH", "BTC"]})
        result = check_hyperliquid(pol, {"coin": "ETH"})
        self.assertTrue(result.allowed)

    def test_not_allowed(self) -> None:
        pol = Policy(extra={"allowed_coins": ["ETH", "BTC"]})
        result = check_hyperliquid(pol, {"coin": "DOGE"})
        self.assertFalse(result.allowed)
        self.assertEqual(result.violations[0].rule, "allowed_coins")

    def test_case_insensitive(self) -> None:
        pol = Policy(extra={"allowed_coins": ["ETH"]})
        result = check_hyperliquid(pol, {"coin": "eth"})
        self.assertTrue(result.allowed)


class TestLoadPolicyProject(unittest.TestCase):
    """load_policy defaults to hyperliquid-autopilot project."""

    def test_project_overlay(self) -> None:
        data = {
            "global": {"max_amount": 1000},
            "hyperliquid-autopilot": {
                "max_amount": 200,
                "max_leverage": 5,
                "allowed_coins": ["ETH", "BTC"],
            },
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            pol = load_policy(path)
            self.assertEqual(pol.max_amount, Decimal("200"))
            self.assertEqual(pol.extra.get("max_leverage"), 5)
            self.assertEqual(pol.extra.get("allowed_coins"), ["ETH", "BTC"])
        finally:
            os.unlink(path)


class TestCombinedViolation(unittest.TestCase):
    """Multiple violations from shared + project-specific rules."""

    def test_amount_and_leverage(self) -> None:
        pol = Policy(max_amount=Decimal("50"), extra={"max_leverage": 3})
        result = check_hyperliquid(pol, {"amount": "100", "leverage": 10})
        self.assertFalse(result.allowed)
        rules = {v.rule for v in result.violations}
        self.assertIn("max_amount", rules)
        self.assertIn("max_leverage", rules)


class TestPolicyGateE2E(unittest.TestCase):
    """End-to-end: a real policy file rejects an oversized order before it ever
    reaches exchange.order."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["STAGEFORGE_STATE_DIR"] = self._tmpdir.name
        self.run_id = "hl-policy-gate-001"

        policy_data = {"hyperliquid-autopilot": {"max_amount": 0.5}}
        self._policy_path = os.path.join(self._tmpdir.name, "policy.json")
        with open(self._policy_path, "w", encoding="utf-8") as fh:
            json.dump(policy_data, fh)

        os.environ["POLICY_FILE"] = self._policy_path
        os.environ["AUDIT_RUN_ID"] = self.run_id

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("STAGEFORGE_STATE_DIR", None)
        os.environ.pop("POLICY_FILE", None)
        os.environ.pop("AUDIT_RUN_ID", None)

    def test_over_limit_order_blocked_before_exchange(self) -> None:
        from unittest import mock

        from hyperliquid_autopilot import state_machine
        from hyperliquid_autopilot.order import place_market_order

        with mock.patch("hyperliquid_autopilot.order.make_exchange_client") as mock_exchange_factory:
            mock_exchange = mock.MagicMock()
            mock_exchange_factory.return_value = mock_exchange

            # size 1.0 exceeds policy max_amount 0.5
            with self.assertRaises(RuntimeError):
                place_market_order(coin="ETH", is_buy=True, size=1.0, slippage=0.01)

            mock_exchange.order.assert_not_called()

        state = state_machine.load_state(self.run_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["current_state"], state_machine.STATE_FAILED)


if __name__ == "__main__":
    unittest.main()
