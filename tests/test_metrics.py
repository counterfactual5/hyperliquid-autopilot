"""Tests for drawdown / leaderboard metrics."""
import unittest
from decimal import Decimal

from hyperliquid_autopilot.metrics import (
    drawdown_series,
    max_drawdown,
    rank_drawdown_leaderboard,
)


class TestDrawdownSeries(unittest.TestCase):
    def test_rising_curve_zero_drawdown(self):
        series = drawdown_series([100, 110, 120])
        self.assertEqual(series, [Decimal("0"), Decimal("0"), Decimal("0")])

    def test_decline_reports_positive_pct(self):
        # peak 100 → 80 == 20% drawdown
        series = drawdown_series([100, 80])
        self.assertEqual(series[1], Decimal("20"))

    def test_new_high_resets_drawdown(self):
        series = drawdown_series([100, 50, 120])
        self.assertEqual(series[0], Decimal("0"))
        self.assertEqual(series[1], Decimal("50"))
        self.assertEqual(series[2], Decimal("0"))


class TestMaxDrawdown(unittest.TestCase):
    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            max_drawdown([])

    def test_flat_curve_zero(self):
        stats = max_drawdown([100, 100, 100])
        self.assertEqual(stats.max_drawdown_pct, Decimal("0"))
        self.assertFalse(stats.recovered)

    def test_simple_drawdown(self):
        # 100 → 60 is the worst (40%), then partial recovery to 80
        stats = max_drawdown([100, 80, 60, 80])
        self.assertEqual(stats.max_drawdown_pct, Decimal("40"))
        self.assertEqual(stats.peak_index, 0)
        self.assertEqual(stats.trough_index, 2)
        self.assertEqual(stats.peak_value, Decimal("100"))
        self.assertEqual(stats.trough_value, Decimal("60"))
        # current dd from running peak 100 to last 80 == 20%
        self.assertEqual(stats.current_drawdown_pct, Decimal("20"))
        self.assertFalse(stats.recovered)

    def test_recovered_flag(self):
        # drops then climbs back above the old peak
        stats = max_drawdown([100, 70, 130])
        self.assertEqual(stats.max_drawdown_pct, Decimal("30"))
        self.assertEqual(stats.current_drawdown_pct, Decimal("0"))
        self.assertTrue(stats.recovered)

    def test_second_peak_higher_drawdown(self):
        # peak shifts to 200 before the deepest decline
        stats = max_drawdown([100, 200, 100])
        self.assertEqual(stats.max_drawdown_pct, Decimal("50"))
        self.assertEqual(stats.peak_value, Decimal("200"))

    def test_as_dict(self):
        d = max_drawdown([100, 80]).as_dict()
        self.assertEqual(d["max_drawdown_pct"], "20")
        self.assertIn("recovered", d)


class TestLeaderboard(unittest.TestCase):
    def test_ranks_smaller_drawdown_first(self):
        board = rank_drawdown_leaderboard({
            "steady": [100, 99, 101, 105],      # tiny dd
            "volatile": [100, 50, 120],         # 50% dd
            "moderate": [100, 90, 110],         # 10% dd
        })
        self.assertEqual([e.name for e in board], ["steady", "moderate", "volatile"])
        self.assertEqual(board[0].rank, 1)
        self.assertEqual(board[2].rank, 3)

    def test_tie_break_by_final_equity(self):
        board = rank_drawdown_leaderboard({
            "a": [100, 90, 100],   # 10% dd, final 100
            "b": [100, 90, 130],   # 10% dd, final 130 → better
        })
        self.assertEqual(board[0].name, "b")
        self.assertEqual(board[1].name, "a")

    def test_entries_are_serializable(self):
        board = rank_drawdown_leaderboard({"x": [100, 80]})
        d = board[0].as_dict()
        self.assertEqual(d["rank"], 1)
        self.assertEqual(d["name"], "x")
        self.assertEqual(d["max_drawdown_pct"], "20")
        self.assertEqual(d["final_equity"], "80")


if __name__ == "__main__":
    unittest.main()
