"""Market-data snapshot validation.

Guards every trade path against acting on degenerate or internally
inconsistent order-book data: missing/zero/negative prices, an empty or
one-sided book, a crossed book (bid > ask), a blown-out spread, or a mid
price that disagrees with the live book (a classic stale / bad-feed signal).

This is the deterministic equivalent of the market-data snapshot checks that
keep an LLM trading loop from acting on hallucinated prices: here the data
comes from the venue, but the same "never trade on a snapshot that fails a
sanity check" discipline applies. Pure stdlib + Decimal, no network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from hyperliquid_autopilot.common import parse_decimal

# Reject books whose top-of-book spread exceeds this. 5% is already extreme
# for a liquid perp; anything wider almost certainly means a broken feed.
DEFAULT_MAX_SPREAD_BPS = Decimal("500")

# How far the reported mid may sit outside the [best_bid, best_ask] band
# (as a fraction of mid) before we treat the snapshot as inconsistent.
DEFAULT_MID_BAND_BPS = Decimal("500")

_BPS = Decimal("10000")


class MarketDataError(ValueError):
    """Raised when a market-data snapshot is not safe to trade on."""


@dataclass
class SnapshotCheck:
    """Structured result of validating one market-data snapshot."""

    ok: bool
    coin: str
    mid: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    spread_bps: Decimal | None = None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        def _txt(v: Decimal | None) -> str | None:
            return format(v, "f") if isinstance(v, Decimal) else None

        return {
            "ok": self.ok,
            "coin": self.coin,
            "mid": _txt(self.mid),
            "best_bid": _txt(self.best_bid),
            "best_ask": _txt(self.best_ask),
            "spread_bps": _txt(self.spread_bps),
            "reasons": list(self.reasons),
        }


def _top_of_book(book: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    """Return (best_bid, best_ask) from an L2 snapshot, or None when absent.

    Layout matches the Hyperliquid Info client: ``levels[0]`` is the bid side
    and ``levels[1]`` is the ask side, each an ordered list of ``{px, sz}``.
    """
    levels = (book or {}).get("levels") or []
    bids = levels[0] if len(levels) > 0 else []
    asks = levels[1] if len(levels) > 1 else []

    def _best(side: list[Any]) -> Decimal | None:
        if not side:
            return None
        try:
            return parse_decimal(str(side[0].get("px", "0")), "px")
        except (ValueError, AttributeError):
            return None

    return _best(bids), _best(asks)


def validate_market_snapshot(
    coin: str,
    mid: Decimal | int | float | str | None,
    book: dict[str, Any] | None,
    *,
    max_spread_bps: Decimal = DEFAULT_MAX_SPREAD_BPS,
    mid_band_bps: Decimal = DEFAULT_MID_BAND_BPS,
) -> SnapshotCheck:
    """Validate a market-data snapshot without raising.

    Returns a :class:`SnapshotCheck`; ``ok`` is False when any sanity rule
    fails, with human-readable ``reasons``.
    """
    reasons: list[str] = []

    mid_dec: Decimal | None
    try:
        mid_dec = parse_decimal(str(mid), f"mid_{coin}") if mid is not None else None
    except ValueError:
        mid_dec = None
        reasons.append(f"mid price for {coin} is not a number: {mid!r}")

    if mid_dec is None and not reasons:
        reasons.append(f"mid price for {coin} is missing")
    elif mid_dec is not None and mid_dec <= 0:
        reasons.append(f"mid price for {coin} is not positive: {mid_dec}")

    best_bid, best_ask = _top_of_book(book or {})
    if best_bid is None:
        reasons.append(f"order book for {coin} has no bid side")
    elif best_bid <= 0:
        reasons.append(f"best bid for {coin} is not positive: {best_bid}")
    if best_ask is None:
        reasons.append(f"order book for {coin} has no ask side")
    elif best_ask <= 0:
        reasons.append(f"best ask for {coin} is not positive: {best_ask}")

    spread_bps: Decimal | None = None
    if best_bid and best_ask and best_bid > 0 and best_ask > 0:
        if best_bid > best_ask:
            reasons.append(
                f"crossed book for {coin}: bid {best_bid} > ask {best_ask}"
            )
        else:
            ref = mid_dec if (mid_dec and mid_dec > 0) else (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) / ref * _BPS
            if spread_bps > max_spread_bps:
                reasons.append(
                    f"spread for {coin} too wide: {spread_bps:.1f}bps "
                    f"> {max_spread_bps}bps"
                )

        # Mid must agree with the live book: a mid far outside [bid, ask]
        # signals a stale or inconsistent feed even when each value looks fine.
        if mid_dec and mid_dec > 0 and best_bid <= best_ask:
            band = mid_dec * mid_band_bps / _BPS
            if mid_dec < best_bid - band or mid_dec > best_ask + band:
                reasons.append(
                    f"mid {mid_dec} for {coin} diverges from book "
                    f"[{best_bid}, {best_ask}] beyond {mid_band_bps}bps"
                )

    return SnapshotCheck(
        ok=not reasons,
        coin=coin,
        mid=mid_dec,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        reasons=reasons,
    )


def assert_tradeable_snapshot(
    coin: str,
    mid: Decimal | int | float | str | None,
    book: dict[str, Any] | None,
    *,
    max_spread_bps: Decimal = DEFAULT_MAX_SPREAD_BPS,
    mid_band_bps: Decimal = DEFAULT_MID_BAND_BPS,
) -> SnapshotCheck:
    """Validate a snapshot and raise :class:`MarketDataError` when unsafe.

    Returns the passing :class:`SnapshotCheck` so callers can reuse the
    parsed top-of-book values.
    """
    check = validate_market_snapshot(
        coin, mid, book, max_spread_bps=max_spread_bps, mid_band_bps=mid_band_bps
    )
    if not check.ok:
        raise MarketDataError(
            f"unsafe market snapshot for {coin}: " + "; ".join(check.reasons)
        )
    return check
