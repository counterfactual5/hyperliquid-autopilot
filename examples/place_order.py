#!/usr/bin/env python3
"""Example: Place a market order on Hyperliquid.

Requires environment variables:
  HYPERLIQUID_PRIVATE_KEY - Your wallet private key
  HYPERLIQUID_WALLET_ADDRESS - Your wallet address
  HYPERLIQUID_TESTNET=1 - (optional) Use testnet
"""
import json
from hyperliquid_autopilot.flow import run_trade_flow

# Dry run first — just get a quote, no actual order
result = run_trade_flow(
    coin="ETH",
    side="buy",
    size_usd=100,
    order_type="market",
    dry_run=True,
)
print("=== Dry Run ===")
print(json.dumps(result, indent=2))

# Uncomment to actually place the order:
# result = run_trade_flow(
#     coin="ETH",
#     side="buy",
#     size_usd=100,
#     order_type="market",
#     slippage=0.01,
# )
# print("=== Live Order ===")
# print(json.dumps(result, indent=2))
