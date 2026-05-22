#!/usr/bin/env python3
"""Example: Get a quote for ETH on Hyperliquid."""
import json
from hyperliquid_autopilot.quote import get_mid_price, prepare_quote, summarize_quote

coin = "ETH"
mid = get_mid_price(coin)
print(f"{coin} mid price: ${mid:,.2f}")

quote = prepare_quote(coin=coin, is_buy=True, size_usd=1000)
print("\nFull quote:")
print(json.dumps(quote, indent=2))

summary = summarize_quote(quote)
print("\nSummary:")
print(json.dumps(summary, indent=2))
