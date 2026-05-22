"""Hyperliquid Autopilot — shared utilities and configuration."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def require_private_key() -> str:
    """Return the Hyperliquid wallet private key from env."""
    key = os.environ.get("HYPERLIQUID_PRIVATE_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "HYPERLIQUID_PRIVATE_KEY not set. Export it as an environment variable."
        )
    if not key.startswith("0x"):
        key = "0x" + key
    return key


def require_wallet_address() -> str:
    """Return the Hyperliquid wallet address for the current network."""
    if is_testnet():
        addr = os.environ.get("HYPERLIQUID_WALLET_ADDRESS_TESTNET", "").strip()
        if not addr:
            addr = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "").strip()
    else:
        addr = os.environ.get("HYPERLIQUID_WALLET_ADDRESS_MAINNET", "").strip()
        if not addr:
            addr = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "").strip()

    if not addr:
        raise RuntimeError(
            "HYPERLIQUID_WALLET_ADDRESS not set. "
            f"Set HYPERLIQUID_WALLET_ADDRESS_{'TESTNET' if is_testnet() else 'MAINNET'} "
            "or HYPERLIQUID_WALLET_ADDRESS."
        )
    if not addr.startswith("0x"):
        addr = "0x" + addr
    return addr


def get_base_url() -> str:
    """Return the API URL (testnet if HYPERLIQUID_TESTNET=1)."""
    if os.environ.get("HYPERLIQUID_TESTNET", "").strip() in ("1", "true", "yes"):
        return TESTNET_URL
    return MAINNET_URL


def is_testnet() -> bool:
    return get_base_url() == TESTNET_URL


# ---------------------------------------------------------------------------
# SDK helpers
# ---------------------------------------------------------------------------

def _fix_spot_meta_tokens(spot_meta: dict[str, Any]) -> dict[str, Any]:
    """Fix spot_meta tokens array to be index-accessible (workaround for testnet API bug)."""
    if "tokens" not in spot_meta:
        return spot_meta

    tokens = spot_meta["tokens"]
    if not tokens:
        return spot_meta

    try:
        if all(tokens[i]["index"] == i for i in range(min(5, len(tokens)))):
            max_index = max(t["index"] for t in tokens)
            if len(tokens) >= max_index + 1:
                return spot_meta
    except (KeyError, IndexError):
        pass

    max_index = max(t["index"] for t in tokens)
    fixed_tokens = [None] * (max_index + 1)
    for token in tokens:
        idx = token["index"]
        if idx < len(fixed_tokens):
            fixed_tokens[idx] = token

    spot_meta = dict(spot_meta)
    spot_meta["tokens"] = fixed_tokens
    return spot_meta


def make_info_client(base_url: str | None = None) -> Any:
    """Create a read-only Info client."""
    from hyperliquid.info import Info

    url = base_url or get_base_url()

    if is_testnet():
        import json
        import urllib.request
        payload = json.dumps({"type": "spotMeta"}).encode("utf-8")
        req = urllib.request.Request(
            url + "/info",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            spot_meta = json.loads(resp.read().decode("utf-8"))
        spot_meta = _fix_spot_meta_tokens(spot_meta)
        return Info(url, skip_ws=True, spot_meta=spot_meta)

    return Info(url, skip_ws=True)


def make_exchange_client(base_url: str | None = None, private_key: str | None = None) -> Any:
    """Create an Exchange client for trading.

    Requires HYPERLIQUID_PRIVATE_KEY to be set in the environment, or passed
    via the *private_key* argument.
    """
    from hyperliquid.exchange import Exchange

    url = base_url or get_base_url()
    wallet = require_wallet_address()

    key = private_key or os.environ.get("HYPERLIQUID_PRIVATE_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "HYPERLIQUID_PRIVATE_KEY not set. Export it as an environment variable."
        )
    if not key.startswith("0x"):
        key = "0x" + key
    return Exchange(url, wallet=wallet, account=wallet, secret=key)


# ---------------------------------------------------------------------------
# Decimal utilities
# ---------------------------------------------------------------------------

def decimal_to_text(value: Decimal) -> str:
    return f"{value:f}"


def parse_decimal(value: Any, label: str = "") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        raise ValueError(f"invalid decimal value{f' for {label}' if label else ''}: {value!r}")
