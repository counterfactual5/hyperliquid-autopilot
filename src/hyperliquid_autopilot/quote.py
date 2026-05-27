"""Hyperliquid quote interface — market data and price estimation."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from hyperliquid_autopilot.common import (
    make_info_client,
    parse_decimal,
    decimal_to_text,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def require_api_key() -> str:
    """Compatibility shim — returns the private key for HL."""
    from hyperliquid_autopilot.common import require_private_key
    return require_private_key()


def get_mid_price(coin: str, base_url: str | None = None) -> Decimal:
    """Return the current mid price for a coin (e.g. 'ETH', 'BTC')."""
    info = make_info_client(base_url)
    all_mids = info.all_mids()
    price_str = all_mids.get(coin)
    if price_str is None:
        raise ValueError(f"No mid price found for {coin}. Available: {list(all_mids.keys())[:10]}")
    return parse_decimal(price_str, f"mid_price_{coin}")


def get_l2_snapshot(coin: str, base_url: str | None = None) -> dict[str, Any]:
    """Return the L2 order book snapshot for a coin."""
    info = make_info_client(base_url)
    return info.l2_snapshot(name=coin)


def get_meta(base_url: str | None = None) -> dict[str, Any]:
    """Return exchange metadata (all coins, decimals, etc.)."""
    info = make_info_client(base_url)
    return info.meta()


# ---------------------------------------------------------------------------
# Quote — estimate output / slippage
# ---------------------------------------------------------------------------

def prepare_quote(
    *,
    coin: str = "ETH",
    is_buy: bool = True,
    size_usd: float | Decimal | str = 100,
    slippage: float = 0.005,  # noqa: ARG001 — reserved for future slippage guard
    base_url: str | None = None,
) -> dict[str, Any]:
    """Estimate a trade quote based on current orderbook."""
    size = parse_decimal(str(size_usd), "size_usd")
    info = make_info_client(base_url=base_url)

    all_mids = info.all_mids()
    mid_str = all_mids.get(coin)
    if mid_str is None:
        raise ValueError(f"Unknown coin: {coin}")
    mid_price = parse_decimal(mid_str, f"mid_{coin}")

    book = info.l2_snapshot(name=coin)
    levels = book.get("levels", [[]])
    if is_buy:
        levels_to_walk = levels[1] if len(levels) > 1 else []
    else:
        levels_to_walk = levels[0] if len(levels) > 0 else []

    filled = Decimal("0")
    remaining = size
    total_cost = Decimal("0")
    best_price = None
    worst_price = None

    for level in levels_to_walk:
        px = parse_decimal(level.get("px", "0"), "px")
        sz = parse_decimal(level.get("sz", "0"), "sz")
        if best_price is None:
            best_price = px

        level_value = px * sz
        if remaining <= level_value:
            total_cost += remaining
            worst_price = px
            filled += remaining / px
            remaining = Decimal("0")
            break
        else:
            total_cost += level_value
            filled += sz
            remaining -= level_value
            worst_price = px

    if best_price and worst_price and mid_price > 0:
        if is_buy:
            impact_bps = (worst_price - mid_price) / mid_price * Decimal("10000")
        else:
            impact_bps = (mid_price - worst_price) / mid_price * Decimal("10000")
    else:
        impact_bps = Decimal("0")

    avg_fill_price = (total_cost / filled) if filled > 0 else mid_price
    slippage_cost_usd = total_cost - (filled * mid_price) if is_buy else (filled * mid_price) - total_cost

    return {
        "coin": coin,
        "side": "buy" if is_buy else "sell",
        "size_usd": decimal_to_text(size),
        "mid_price": decimal_to_text(mid_price),
        "estimated_fill_price": decimal_to_text(avg_fill_price),
        "estimated_fill_size": decimal_to_text(filled),
        "slippage_bps": decimal_to_text(impact_bps),
        "slippage_cost_usd": decimal_to_text(slippage_cost_usd),
        "book_depth_ask": sum(1 for _ in (levels[1] if len(levels) > 1 else [])),
        "book_depth_bid": sum(1 for _ in (levels[0] if len(levels) > 0 else [])),
        "filled_pct": decimal_to_text((size - remaining) / size * 100) if size > 0 else "0",
        "venue": "hyperliquid",
    }


def summarize_quote(raw_quote: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw quote into a standard summary."""
    return {
        "routing": "HYPERLIQUID_PERP",
        "outputAmount": raw_quote.get("estimated_fill_size"),
        "gasFee": "0",
        "gasFeeUSD": "0",
        "priceImpact": raw_quote.get("slippage_bps", "0"),
        "midPrice": raw_quote.get("mid_price"),
        "fillPrice": raw_quote.get("estimated_fill_price"),
        "venue": "hyperliquid",
    }
