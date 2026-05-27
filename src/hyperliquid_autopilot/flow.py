"""Hyperliquid trade flow — end-to-end quote → execute orchestration."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from hyperliquid_autopilot.common import (
    decimal_to_text,
    get_base_url,
    is_testnet,
    parse_decimal,
    require_wallet_address,
)
from hyperliquid_autopilot.quote import get_mid_price, prepare_quote, summarize_quote
from hyperliquid_autopilot.order import (
    place_limit_order,
    place_market_order,
    set_leverage,
)


# ---------------------------------------------------------------------------
# Trade flow
# ---------------------------------------------------------------------------

def run_trade_flow(
    *,
    coin: str,
    side: str,
    size_usd: float | Decimal | str,
    order_type: str = "market",
    limit_price: float | Decimal | str | None = None,
    leverage: int | None = None,
    slippage: float = 0.01,
    time_in_force: str = "Gtc",
    dry_run: bool = False,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Execute a complete trade flow.

    Steps:
      1. Validate parameters
      2. Optionally set leverage
      3. Get quote / price estimate
      4. If dry_run, stop here and return the quote
      5. Place the order
      6. Return execution result

    Parameters
    ----------
    coin : str
        Asset symbol (e.g. "ETH", "BTC")
    side : str
        "buy" or "sell"
    size_usd : float or Decimal or str
        Trade size in USD
    order_type : str
        "market" (IOC) or "limit"
    limit_price : float, optional
        Required for limit orders
    leverage : int, optional
        Set leverage before trading
    slippage : float
        Slippage tolerance for market orders (default 1%)
    dry_run : bool
        If True, only get a quote without placing the order
    """
    url = base_url or get_base_url()
    size = parse_decimal(str(size_usd), "size_usd")
    is_buy = side.lower().strip() in ("buy", "long")

    # --- Pre-flight ---
    wallet = require_wallet_address()
    mid = get_mid_price(coin, base_url=url)

    # --- Set leverage if requested ---
    leverage_result = None
    if leverage is not None:
        leverage_result = set_leverage(coin=coin, leverage=leverage, base_url=url)

    # --- Quote ---
    quote = prepare_quote(
        coin=coin,
        is_buy=is_buy,
        size_usd=size,
        slippage=slippage,
        base_url=url,
    )
    quote_summary = summarize_quote(quote)

    result: dict[str, Any] = {
        "action": "hyperliquid_trade_flow",
        "coin": coin,
        "side": side,
        "size_usd": decimal_to_text(size),
        "order_type": order_type,
        "mid_price": decimal_to_text(mid),
        "quote": quote_summary,
        "wallet": wallet[:10] + "..." + wallet[-6:],
        "venue": "hyperliquid",
        "network": "testnet" if is_testnet() else "mainnet",
        "dry_run": dry_run,
    }

    if leverage_result:
        result["leverage"] = leverage_result

    if dry_run:
        result["status"] = "dry_run"
        return result

    # --- Execute ---
    if order_type == "market":
        size_in_coin = size / mid
        exec_result = place_market_order(
            coin=coin,
            is_buy=is_buy,
            size=size_in_coin,
            slippage=slippage,
            base_url=url,
        )
    elif order_type == "limit":
        if limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        size_in_coin = size / parse_decimal(str(limit_price), "limit_price")
        exec_result = place_limit_order(
            coin=coin,
            is_buy=is_buy,
            size=size_in_coin,
            price=limit_price,
            time_in_force=time_in_force,
            base_url=url,
        )
    else:
        raise ValueError(f"Unknown order_type: {order_type}")

    result["execution"] = exec_result
    result["status"] = exec_result.get("status", "unknown")

    return result
