"""Hyperliquid order execution — place, cancel, position management."""

from __future__ import annotations

import os
import time
import uuid
from decimal import Decimal
from typing import Any

from hyperliquid_autopilot import policy as _policy
from hyperliquid_autopilot import state_machine
from hyperliquid_autopilot.audit import (
    EVENT_BROADCAST,
    EVENT_CANCEL,
    EVENT_ERROR,
    EVENT_PREFLIGHT,
    EVENT_SIGN,
    log_event,
)
from hyperliquid_autopilot.common import (
    decimal_to_text,
    get_base_url,
    make_exchange_client,
    make_info_client,
    parse_decimal,
    require_wallet_address,
)

MAX_SLIPPAGE = Decimal("0.20")
_last_run_id: str = ""


class OrderExecutionError(RuntimeError):
    """Structured execution error with operation context."""

    def __init__(self, operation: str, coin: str, details: str):
        self.operation = operation
        self.coin = coin
        self.details = details
        super().__init__(f"{operation}({coin}) failed: {details}")


def _parse_slippage(slippage: float | Decimal | str) -> Decimal:
    slippage_dec = parse_decimal(str(slippage), "slippage")
    if slippage_dec <= 0:
        raise ValueError("slippage must be > 0")
    if slippage_dec > MAX_SLIPPAGE:
        raise ValueError(f"slippage must be <= {MAX_SLIPPAGE}")
    return slippage_dec


def _retry_call(
    operation: str, coin: str, fn, *, retries: int = 3, backoff_seconds: float = 0.5
):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(backoff_seconds * attempt)
    # --- state machine: failed (let errors surface) ---
    state_machine.transition(
        _last_run_id,
        state_machine.STATE_FAILED,
        payload={
            "error_code": type(last_error).__name__ if last_error else "retry_exhausted"
        },
    )
    log_event(
        event=EVENT_ERROR,
        chain="hyperliquid",
        wallet=_try_wallet(),
        error_code=type(last_error).__name__ if last_error else "retry_exhausted",
        details={
            "operation": operation,
            "coin": coin,
            "retries": retries,
            "message": str(last_error) if last_error else "unknown",
        },
    )
    raise OrderExecutionError(operation, coin, str(last_error))


def _try_wallet() -> str | None:
    """Look up the wallet address without raising — audit must never break trade.

    The wallet helper raises when env vars are missing; audit logging should
    degrade gracefully in that case rather than masking the original error.
    """
    try:
        return require_wallet_address()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def get_positions(base_url: str | None = None) -> list[dict[str, Any]]:
    """Return all open positions."""
    info = make_info_client(base_url)
    wallet = require_wallet_address()
    state = info.user_state(wallet)
    positions = []
    for p in state.get("assetPositions", []):
        pos = p.get("position", {})
        if pos.get("szi") and parse_decimal(pos["szi"]) != 0:
            positions.append(
                {
                    "coin": pos.get("coin"),
                    "size": pos.get("szi"),
                    "entryPrice": pos.get("entryPx"),
                    "unrealizedPnl": pos.get("unrealizedPnl"),
                    "leverage": p.get("leverage", {}).get("value"),
                    "marginUsed": pos.get("marginUsed"),
                    "liquidationPrice": pos.get("liquidationPx"),
                }
            )
    return positions


def get_open_orders(
    coin: str | None = None, base_url: str | None = None
) -> list[dict[str, Any]]:
    """Return open orders, optionally filtered by coin."""
    info = make_info_client(base_url)
    wallet = require_wallet_address()
    orders = info.open_orders(wallet)
    if coin:
        orders = [o for o in orders if o.get("coin") == coin]
    return orders


def get_account_value(base_url: str | None = None) -> dict[str, Any]:
    """Return account value summary."""
    info = make_info_client(base_url)
    wallet = require_wallet_address()
    state = info.user_state(wallet)
    margin = state.get("marginSummary", {})
    return {
        "totalAccountValue": margin.get("accountValue"),
        "totalMarginUsed": margin.get("totalMarginUsed"),
        "totalNtlPos": margin.get("totalNtlPos"),
        "totalRawUsd": margin.get("totalRawUsd"),
    }


# ---------------------------------------------------------------------------
# Order execution
# ---------------------------------------------------------------------------


def place_market_order(
    *,
    coin: str,
    is_buy: bool,
    size: float | Decimal | str,
    slippage: float = 0.01,
    cloid: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Place a market order (IOC at limit price with slippage buffer)."""
    size_dec = parse_decimal(str(size), "size")
    slippage_dec = _parse_slippage(slippage)

    # --- state machine: preflight ---
    global _last_run_id
    _last_run_id = (
        os.environ.get("AUDIT_RUN_ID")
        or os.environ.get("STAGEFORGE_RUN_ID")
        or f"hl-{uuid.uuid4().hex[:12]}"
    )
    run_id = _last_run_id
    action = state_machine.next_action(run_id)
    if action is None:
        raise RuntimeError(f"run {run_id} is in terminal state — cannot proceed")
    if action == state_machine.STATE_PREFLIGHT:
        state_machine.transition(
            run_id,
            state_machine.STATE_PREFLIGHT,
            payload={"coin": coin, "side": "buy" if is_buy else "sell"},
        )

    # --- policy gate (PREFLIGHT → SIGNED) ---
    pol = _policy.load_policy()
    policy_ctx = {
        "amount": str(size),
        "chain": "hyperliquid",
        "sender": _try_wallet(),
        "coin": coin,
        "slippage_bps": int(slippage * 10000) if slippage else None,
    }
    policy_result = _policy.check_hyperliquid(pol, policy_ctx)
    if not policy_result.allowed:
        state_machine.transition(run_id, state_machine.STATE_FAILED,
                                 payload={"policy_violations": policy_result.to_dict()["violations"]})
        log_event(
            event=EVENT_ERROR,
            chain="hyperliquid",
            wallet=_try_wallet(),
            error_code="policy_rejected",
            details={"violations": policy_result.to_dict()["violations"]},
        )
        raise RuntimeError(
            f"Policy rejected: {'; '.join(v.message for v in policy_result.violations)}"
        )
    if policy_result.warnings:
        log_event(
            event=EVENT_PREFLIGHT,
            chain="hyperliquid",
            wallet=_try_wallet(),
            details={"stage": "policy", "warnings": policy_result.to_dict()["warnings"]},
        )

    action = state_machine.next_action(run_id)
    if action is None:
        raise RuntimeError(f"run {run_id} is in terminal state — cannot proceed")
    if action == state_machine.STATE_BROADCAST:
        return {
            "action": "place_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "status": "already_broadcast",
            "venue": "hyperliquid",
        }
    if action == state_machine.STATE_CONFIRMED:
        return {
            "action": "place_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "status": "already_confirmed",
            "venue": "hyperliquid",
        }
    if action != state_machine.STATE_SIGNED:
        raise RuntimeError(f"unexpected next_action={action!r} before signing")

    exchange = make_exchange_client(base_url)

    info = make_info_client(base_url or get_base_url())
    all_mids = info.all_mids()
    mid = parse_decimal(all_mids[coin], f"mid_{coin}")

    if is_buy:
        limit_price = mid * (1 + slippage_dec)
    else:
        limit_price = mid * (1 - slippage_dec)

    wallet = _try_wallet()
    log_event(
        event=EVENT_SIGN,
        chain="hyperliquid",
        wallet=wallet,
        details={
            "operation": "place_market_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "size": decimal_to_text(size_dec),
            "limitPrice": decimal_to_text(limit_price),
            "slippage": decimal_to_text(slippage_dec),
            "cloid": cloid,
        },
    )
    # --- state machine: signed ---
    state_machine.transition(run_id, state_machine.STATE_SIGNED)
    result = _retry_call(
        "place_market_order",
        coin,
        lambda: exchange.order(
            coin=coin,
            is_buy=is_buy,
            sz=float(size_dec),
            limit_px=float(limit_price),
            order_type={"limit": {"tif": "IOC"}},
            cloid=cloid,
        ),
    )
    log_event(
        event=EVENT_BROADCAST,
        chain="hyperliquid",
        wallet=wallet,
        details={
            "operation": "place_market_order",
            "coin": coin,
            "status": _parse_status(result),
        },
    )
    # --- state machine: broadcast ---
    state_machine.transition(run_id, state_machine.STATE_BROADCAST)

    return _normalize_order_result(
        result, coin, is_buy, size_dec, limit_price, "market_ioc"
    )


def place_limit_order(
    *,
    coin: str,
    is_buy: bool,
    size: float | Decimal | str,
    price: float | Decimal | str,
    time_in_force: str = "Gtc",
    cloid: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Place a limit order (Gtc, Ioc, or Alo)."""
    size_dec = parse_decimal(str(size), "size")
    price_dec = parse_decimal(str(price), "price")

    global _last_run_id
    _last_run_id = (
        os.environ.get("AUDIT_RUN_ID")
        or os.environ.get("STAGEFORGE_RUN_ID")
        or f"hl-{uuid.uuid4().hex[:12]}"
    )
    run_id = _last_run_id
    action = state_machine.next_action(run_id)
    if action is None:
        raise RuntimeError(f"run {run_id} is in terminal state — cannot proceed")
    if action == state_machine.STATE_PREFLIGHT:
        state_machine.transition(
            run_id,
            state_machine.STATE_PREFLIGHT,
            payload={"coin": coin, "side": "buy" if is_buy else "sell", "tif": time_in_force},
        )

    # --- policy gate (PREFLIGHT → SIGNED) ---
    pol = _policy.load_policy()
    policy_ctx = {
        "amount": str(size_dec),
        "chain": "hyperliquid",
        "sender": _try_wallet(),
        "coin": coin,
    }
    policy_result = _policy.check_hyperliquid(pol, policy_ctx)
    if not policy_result.allowed:
        state_machine.transition(run_id, state_machine.STATE_FAILED,
                                 payload={"policy_violations": policy_result.to_dict()["violations"]})
        log_event(
            event=EVENT_ERROR,
            chain="hyperliquid",
            wallet=_try_wallet(),
            error_code="policy_rejected",
            details={"violations": policy_result.to_dict()["violations"]},
        )
        raise RuntimeError(
            f"Policy rejected: {'; '.join(v.message for v in policy_result.violations)}"
        )
    if policy_result.warnings:
        log_event(
            event=EVENT_PREFLIGHT,
            chain="hyperliquid",
            wallet=_try_wallet(),
            details={"stage": "policy", "warnings": policy_result.to_dict()["warnings"]},
        )

    action = state_machine.next_action(run_id)
    if action is None:
        raise RuntimeError(f"run {run_id} is in terminal state — cannot proceed")
    if action == state_machine.STATE_BROADCAST:
        return {
            "action": "place_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "status": "already_broadcast",
            "venue": "hyperliquid",
        }
    if action == state_machine.STATE_CONFIRMED:
        return {
            "action": "place_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "status": "already_confirmed",
            "venue": "hyperliquid",
        }
    if action != state_machine.STATE_SIGNED:
        raise RuntimeError(f"unexpected next_action={action!r} before signing")

    exchange = make_exchange_client(base_url)

    wallet = _try_wallet()
    log_event(
        event=EVENT_SIGN,
        chain="hyperliquid",
        wallet=wallet,
        details={
            "operation": "place_limit_order",
            "coin": coin,
            "side": "buy" if is_buy else "sell",
            "size": decimal_to_text(size_dec),
            "price": decimal_to_text(price_dec),
            "tif": time_in_force,
            "cloid": cloid,
        },
    )
    state_machine.transition(run_id, state_machine.STATE_SIGNED)
    result = _retry_call(
        "place_limit_order",
        coin,
        lambda: exchange.order(
            coin=coin,
            is_buy=is_buy,
            sz=float(size_dec),
            limit_px=float(price_dec),
            order_type={"limit": {"tif": time_in_force}},
            cloid=cloid,
        ),
    )
    log_event(
        event=EVENT_BROADCAST,
        chain="hyperliquid",
        wallet=wallet,
        details={
            "operation": "place_limit_order",
            "coin": coin,
            "status": _parse_status(result),
        },
    )
    state_machine.transition(run_id, state_machine.STATE_BROADCAST)

    return _normalize_order_result(
        result, coin, is_buy, size_dec, price_dec, f"limit_{time_in_force}"
    )


def cancel_order(
    *,
    coin: str,
    order_id: int,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Cancel a single order."""
    exchange = make_exchange_client(base_url)
    result = _retry_call(
        "cancel_order", coin, lambda: exchange.cancel(coin=coin, oid=order_id)
    )
    log_event(
        event=EVENT_CANCEL,
        chain="hyperliquid",
        wallet=_try_wallet(),
        details={
            "operation": "cancel_order",
            "coin": coin,
            "orderId": order_id,
            "status": _parse_status(result),
        },
    )
    return {
        "action": "cancel_order",
        "coin": coin,
        "orderId": order_id,
        "status": _parse_status(result),
        "raw": result,
    }


def cancel_all_orders(
    *,
    coin: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Cancel all open orders (optionally for a specific coin)."""
    exchange = make_exchange_client(base_url)

    if coin:
        open_orders = get_open_orders(coin=coin, base_url=base_url)
        oids = [o.get("oid") for o in open_orders if "oid" in o]
        if not oids:
            return {"action": "cancel_all", "coin": coin, "cancelled": 0}
        result = exchange.bulk_cancel([{"coin": coin, "oid": oid} for oid in oids])
    else:
        wallet = require_wallet_address()
        info = make_info_client(base_url)
        open_orders = info.open_orders(wallet)
        cancels = [
            {"coin": o.get("coin", ""), "oid": o.get("oid")}
            for o in open_orders
            if "oid" in o and "coin" in o
        ]
        if not cancels:
            return {"action": "cancel_all", "cancelled": 0}
        result = exchange.bulk_cancel(cancels)

    return {
        "action": "cancel_all",
        "coin": coin,
        "cancelled": len(result) if isinstance(result, list) else "?",
        "status": _parse_status(result),
        "raw": result,
    }


def set_leverage(
    *,
    coin: str,
    leverage: int,
    is_cross: bool = True,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Set leverage for a coin."""
    exchange = make_exchange_client(base_url)
    leverage_type = "cross" if is_cross else "isolated"
    result = exchange.leverage_update(
        coin=coin,
        leverage=leverage,
        is_cross=is_cross,
    )
    return {
        "action": "set_leverage",
        "coin": coin,
        "leverage": leverage,
        "type": leverage_type,
        "status": _parse_status(result),
        "raw": result,
    }


def close_position(
    *,
    coin: str,
    slippage: float = 0.02,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Close an existing position by placing a reducing market order."""
    positions = get_positions(base_url=base_url)
    target = None
    for p in positions:
        if p["coin"] == coin:
            target = p
            break

    if target is None:
        return {"action": "close_position", "coin": coin, "status": "no_position"}

    size = parse_decimal(target["size"])
    if size == 0:
        return {"action": "close_position", "coin": coin, "status": "no_position"}

    is_buy = size < 0
    close_size = abs(size)

    return place_market_order(
        coin=coin,
        is_buy=is_buy,
        size=close_size,
        slippage=slippage,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_order_result(
    result: Any,
    coin: str,
    is_buy: bool,
    size: Decimal,
    price: Decimal,
    order_type: str,
) -> dict[str, Any]:
    """Normalize SDK response into a standard format."""
    status = _parse_status(result)
    return {
        "action": "place_order",
        "coin": coin,
        "side": "buy" if is_buy else "sell",
        "size": decimal_to_text(size),
        "price": decimal_to_text(price),
        "orderType": order_type,
        "status": status,
        "venue": "hyperliquid",
        "raw": result,
    }


def _parse_status(result: Any) -> str:
    """Parse SDK result into a human-readable status."""
    if isinstance(result, dict):
        status = result.get("status")
        if status == "ok":
            return "ok"
        if status == "err":
            return f"error: {result.get('response', {}).get('error', 'unknown')}"
        response = result.get("response", {})
        if isinstance(response, dict) and "error" in response:
            return f"error: {response['error']}"
    if isinstance(result, str):
        if result == "Success":
            return "ok"
        return result
    return str(result)
