"""Tests for market-data snapshot validation."""
import unittest
from decimal import Decimal

from hyperliquid_autopilot.market_snapshot import (
    MarketDataError,
    SnapshotCheck,
    assert_tradeable_snapshot,
    validate_market_snapshot,
)


def _book(bid="3000.0", ask="3001.0"):
    return {
        "levels": [
            [{"px": bid, "sz": "10"}, {"px": "2999.0", "sz": "5"}],
            [{"px": ask, "sz": "8"}, {"px": "3002.0", "sz": "3"}],
        ]
    }


class TestValidateMarketSnapshot(unittest.TestCase):
    def test_healthy_snapshot_ok(self):
        check = validate_market_snapshot("ETH", "3000.5", _book())
        self.assertTrue(check.ok)
        self.assertEqual(check.reasons, [])
        self.assertEqual(check.best_bid, Decimal("3000.0"))
        self.assertEqual(check.best_ask, Decimal("3001.0"))
        self.assertIsNotNone(check.spread_bps)

    def test_missing_mid(self):
        check = validate_market_snapshot("ETH", None, _book())
        self.assertFalse(check.ok)
        self.assertTrue(any("missing" in r for r in check.reasons))

    def test_non_positive_mid(self):
        check = validate_market_snapshot("ETH", "0", _book())
        self.assertFalse(check.ok)
        self.assertTrue(any("not positive" in r for r in check.reasons))

    def test_empty_book(self):
        check = validate_market_snapshot("ETH", "3000", {"levels": [[], []]})
        self.assertFalse(check.ok)
        self.assertTrue(any("no bid" in r for r in check.reasons))
        self.assertTrue(any("no ask" in r for r in check.reasons))

    def test_one_sided_book(self):
        book = {"levels": [[{"px": "3000", "sz": "1"}], []]}
        check = validate_market_snapshot("ETH", "3000", book)
        self.assertFalse(check.ok)
        self.assertTrue(any("no ask" in r for r in check.reasons))

    def test_crossed_book(self):
        check = validate_market_snapshot("ETH", "3000", _book(bid="3005", ask="2995"))
        self.assertFalse(check.ok)
        self.assertTrue(any("crossed" in r for r in check.reasons))

    def test_spread_too_wide(self):
        # bid 3000 / ask 3600 → 20% spread, far beyond 5% default
        check = validate_market_snapshot("ETH", "3300", _book(bid="3000", ask="3600"))
        self.assertFalse(check.ok)
        self.assertTrue(any("too wide" in r for r in check.reasons))

    def test_mid_diverges_from_book(self):
        # tight book around 3000 but mid reported as 5000 → stale/bad feed
        check = validate_market_snapshot("ETH", "5000", _book())
        self.assertFalse(check.ok)
        self.assertTrue(any("diverges" in r for r in check.reasons))

    def test_custom_spread_tolerance_allows_wide(self):
        check = validate_market_snapshot(
            "ETH", "3300", _book(bid="3000", ask="3600"),
            max_spread_bps=Decimal("5000"), mid_band_bps=Decimal("5000"),
        )
        self.assertTrue(check.ok)


class TestAssertTradeableSnapshot(unittest.TestCase):
    def test_passes_and_returns_check(self):
        check = assert_tradeable_snapshot("ETH", "3000.5", _book())
        self.assertIsInstance(check, SnapshotCheck)
        self.assertTrue(check.ok)

    def test_raises_on_bad_snapshot(self):
        with self.assertRaises(MarketDataError):
            assert_tradeable_snapshot("ETH", "0", {"levels": [[], []]})

    def test_as_dict_serializes(self):
        d = validate_market_snapshot("ETH", "3000.5", _book()).as_dict()
        self.assertEqual(d["coin"], "ETH")
        self.assertEqual(d["best_bid"], "3000.0")
        self.assertIsInstance(d["reasons"], list)


if __name__ == "__main__":
    unittest.main()
