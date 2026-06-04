"""Drawdown and leaderboard metrics.

Venue-agnostic performance math over an equity curve (a time-ordered series
of account-value snapshots): drawdown series, max drawdown, current drawdown,
and a drawdown-ranked leaderboard. Pure stdlib + Decimal so it can run in any
trade-loop or reporting path without extra deps.

The leaderboard ranks *smaller* max drawdown as better, matching the
risk-first "who bled least" view used in trading tournaments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from hyperliquid_autopilot.common import parse_decimal

_HUNDRED = Decimal("100")


def _fmt(v: Decimal) -> str:
    """Format a Decimal without trailing-zero scale artifacts or exponents."""
    return format(v.normalize(), "f")


def _to_decimals(equity: Iterable[Any], label: str = "equity") -> list[Decimal]:
    out: list[Decimal] = []
    for i, v in enumerate(equity):
        out.append(parse_decimal(str(v), f"{label}[{i}]"))
    return out


@dataclass
class DrawdownStats:
    """Summary of the worst peak-to-trough decline in an equity curve."""

    max_drawdown_pct: Decimal          # e.g. Decimal("12.5") == 12.5%
    peak_index: int
    trough_index: int
    peak_value: Decimal
    trough_value: Decimal
    current_drawdown_pct: Decimal      # decline from running peak to last point
    recovered: bool                    # True if the curve climbed back to the peak

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_drawdown_pct": _fmt(self.max_drawdown_pct),
            "peak_index": self.peak_index,
            "trough_index": self.trough_index,
            "peak_value": _fmt(self.peak_value),
            "trough_value": _fmt(self.trough_value),
            "current_drawdown_pct": _fmt(self.current_drawdown_pct),
            "recovered": self.recovered,
        }


def drawdown_series(equity: Sequence[Any]) -> list[Decimal]:
    """Return the running drawdown (as a positive %) at each point.

    Drawdown at point t = (running_peak - value_t) / running_peak * 100, so a
    fresh equity high reports 0 and declines report a positive percentage.
    """
    values = _to_decimals(equity)
    series: list[Decimal] = []
    peak: Decimal | None = None
    for v in values:
        if peak is None or v > peak:
            peak = v
        if peak > 0:
            series.append((peak - v) / peak * _HUNDRED)
        else:
            series.append(Decimal("0"))
    return series


def max_drawdown(equity: Sequence[Any]) -> DrawdownStats:
    """Compute peak-to-trough max drawdown stats over an equity curve.

    Raises ``ValueError`` on an empty series. A flat or strictly rising curve
    yields ``max_drawdown_pct == 0``.
    """
    values = _to_decimals(equity)
    if not values:
        raise ValueError("equity series is empty")

    peak = values[0]
    peak_index = 0
    best_peak_index = 0
    max_dd = Decimal("0")
    trough_index = 0
    dd_peak_value = values[0]
    dd_trough_value = values[0]

    for i, v in enumerate(values):
        if v > peak:
            peak = v
            peak_index = i
        if peak > 0:
            dd = (peak - v) / peak * _HUNDRED
            if dd > max_dd:
                max_dd = dd
                trough_index = i
                best_peak_index = peak_index
                dd_peak_value = peak
                dd_trough_value = v

    running_peak = max(values)
    last = values[-1]
    current_dd = ((running_peak - last) / running_peak * _HUNDRED) if running_peak > 0 else Decimal("0")
    recovered = current_dd == 0 and max_dd > 0

    return DrawdownStats(
        max_drawdown_pct=max_dd,
        peak_index=best_peak_index,
        trough_index=trough_index,
        peak_value=dd_peak_value,
        trough_value=dd_trough_value,
        current_drawdown_pct=current_dd,
        recovered=recovered,
    )


@dataclass
class LeaderboardEntry:
    """One ranked competitor in a drawdown leaderboard."""

    name: str
    max_drawdown_pct: Decimal
    final_equity: Decimal | None = None
    rank: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "name": self.name,
            "max_drawdown_pct": _fmt(self.max_drawdown_pct),
            "final_equity": (_fmt(self.final_equity) if self.final_equity is not None else None),
            **self.extra,
        }


def rank_drawdown_leaderboard(
    curves: dict[str, Sequence[Any]],
    *,
    tie_break_final_equity: bool = True,
) -> list[LeaderboardEntry]:
    """Rank competitors by max drawdown (smaller is better).

    ``curves`` maps competitor name -> equity series. Ties on drawdown are
    broken by larger final equity when ``tie_break_final_equity`` is set.
    """
    entries: list[LeaderboardEntry] = []
    for name, curve in curves.items():
        stats = max_drawdown(curve)
        values = _to_decimals(curve)
        entries.append(
            LeaderboardEntry(
                name=name,
                max_drawdown_pct=stats.max_drawdown_pct,
                final_equity=values[-1] if values else None,
            )
        )

    def _sort_key(e: LeaderboardEntry) -> tuple[Decimal, Decimal]:
        fe = e.final_equity if e.final_equity is not None else Decimal("0")
        # Smaller drawdown first; then larger final equity (negated) first.
        return (e.max_drawdown_pct, -fe if tie_break_final_equity else Decimal("0"))

    entries.sort(key=_sort_key)
    for i, e in enumerate(entries, start=1):
        e.rank = i
    return entries
