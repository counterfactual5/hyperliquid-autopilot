<div align="center">

# 📈 Hyperliquid Autopilot

### Perpetual futures trading, in Python.

**Quotes. Orders. Leverage. Positions.** Everything you need to trade on Hyperliquid.

Built on the Official SDK · Testnet + Mainnet · Market & Limit Orders · Position Management

[![Test](https://github.com/counterfactual5/hyperliquid-autopilot/actions/workflows/test.yml/badge.svg)](https://github.com/counterfactual5/hyperliquid-autopilot/actions)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

[Installation](#installation) · [Quotes](#-get-quotes--market-data) · [Trading](#-place--manage-orders) · [Trade Flow](#-end-to-end-trade-flow)

</div>

---

## What Is This?

[Hyperliquid](https://hyperliquid.xyz) is a high-performance perpetual futures DEX. Their official Python SDK handles the low-level protocol — but it's bare-bones. No quotes, no slippage estimation, no end-to-end trade flows.

**hyperliquid-autopilot wraps the SDK with a practical trading layer:**

```
  Official SDK:      "Here's how to send a raw order to the API"
  hyperliquid-autopilot: "Quote ETH → check slippage → place order → done"
```

---

## Features

- **Market Data** — mid price, L2 orderbook, slippage estimation, available assets
- **Market Orders** — instant execution with size in USD
- **Limit Orders** — place at specific price, with time-in-force options
- **Position Management** — view positions, close positions, set leverage
- **Order Management** — cancel single or all orders, view open orders
- **Trade Flow** — end-to-end: quote → confirm → execute in one call
- **Testnet & Mainnet** — switch with one env var

---

## Installation

```bash
pip install hyperliquid-autopilot
```

This installs the [official Hyperliquid Python SDK](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) as a dependency.

---

## Quick Start

### Configuration

```bash
# Required for trading
export HYPERLIQUID_WALLET_ADDRESS="0x..."
export HYPERLIQUID_PRIVATE_KEY="0x..."   # env var only, never on disk

# Switch to testnet (default is mainnet)
export HYPERLIQUID_TESTNET=1
```

### 📊 Get Quotes & Market Data

```python
from hyperliquid_autopilot.quote import get_mid_price, prepare_quote, get_l2_snapshot

# Current ETH price
mid = get_mid_price("ETH")
print(f"  ETH mid price: ${mid:,.2f}")

# Quote for buying $100 of ETH
quote = prepare_quote(coin="ETH", size_usd=100, is_buy=True)
print(f"  Entry price: ${quote['estimated_fill_price']}")
print(f"  Slippage: {quote['slippage_bps']} bps")

# L2 orderbook depth
book = get_l2_snapshot("ETH")
for level in book["bids"][:3]:
    print(f"  Bid: ${level['px']}  Size: {level['sz']}")
```

```
  ETH mid price: $3,245.50
  Entry price: $3,246.80
  Slippage: 4.0 bps
  Bid: $3,245.00  Size: 12.5
  Bid: $3,244.50  Size: 8.3
  Bid: $3,244.00  Size: 15.1
```

### ⚡ Place & Manage Orders

```python
from hyperliquid_autopilot.order import (
    place_market_order, place_limit_order,
    get_positions, get_open_orders,
    set_leverage, close_position, cancel_order, cancel_all_orders,
)
```

**Open a position:**

```python
# Market buy ETH
result = place_market_order(coin="ETH", is_buy=True, size=0.05)
print(f"  Status: {result['status']}")
print(f"  Filled: {result.get('filled_size')} @ ${result.get('avg_price')}")

# Limit order at specific price
result = place_limit_order(coin="ETH", is_buy=True, price=3000, size=0.1)
print(f"  Order ID: {result['order_id']}")
```

**Manage positions:**

```python
# Set leverage
set_leverage(coin="ETH", leverage=5)

# View positions
positions = get_positions()
for pos in positions:
    print(f"  {pos['coin']}: {pos['side']} {pos['size']} @ entry ${pos['entry_px']}")
    print(f"    PnL: ${pos['unrealized_pnl']}")
    print(f"    Leverage: {pos['leverage']}x")

# Close a position
close_position(coin="ETH")
```

**Manage orders:**

```python
# View open orders
orders = get_open_orders(coin="ETH")
for o in orders:
    print(f"  {o['coin']}: {o['side']} {o['sz']} @ ${o['limit_px']}")

# Cancel specific order
cancel_order(coin="ETH", order_id=12345)

# Cancel all orders for a coin
cancel_all_orders(coin="ETH")
```

### 🔄 End-to-End Trade Flow

```python
from hyperliquid_autopilot.flow import run_trade_flow

# Full flow: quote → confirm → execute
result = run_trade_flow(
    coin="ETH",
    side="buy",
    size_usd=100,
    dry_run=True,        # paper trade mode
)
print(result["summary"])
```

---

## API Reference

### Market Data (quote.py)

| Function | Description |
|---|---|
| `get_mid_price(coin)` | Current mid price |
| `get_l2_snapshot(coin)` | L2 order book (bids + asks) |
| `get_meta()` | All tradeable assets and metadata |
| `prepare_quote(coin, size_usd, is_buy)` | Full quote with slippage estimation |

### Order Execution (order.py)

| Function | Description |
|---|---|
| `place_market_order(coin, is_buy, size)` | Market order by size |
| `place_limit_order(coin, is_buy, price, size)` | Limit order at specific price |
| `cancel_order(coin, order_id)` | Cancel a specific order |
| `cancel_all_orders(coin)` | Cancel all orders for a coin |
| `get_open_orders(coin)` | List open orders |
| `get_positions()` | List all positions with PnL |
| `get_account_value()` | Account equity and margin |
| `set_leverage(coin, leverage)` | Set leverage for a coin |
| `close_position(coin)` | Close entire position |

### Trade Flow (flow.py)

| Function | Description |
|---|---|
| `run_trade_flow(coin, is_buy, size, ...)` | End-to-end: quote → confirm → execute |

### Configuration (common.py)

| Function | Description |
|---|---|
| `get_base_url()` | API URL (testnet or mainnet) |
| `is_testnet()` | Check testnet mode |
| `make_info_client()` | Create SDK Info client |
| `make_exchange_client()` | Create SDK Exchange client |

---

## Architecture

```
hyperliquid_autopilot/
├── quote.py       Market data — prices, orderbook, slippage
├── order.py       Order execution — market, limit, cancel, positions
├── common.py      Shared utilities — env config, SDK client creation
└── flow.py        End-to-end trade orchestration

Data Flow:

  User Code
     │
     ├── quote.prepare_quote("ETH", 100, "buy")
     │       │
     │       └── Hyperliquid Info API → mid price + L2 book → slippage calc
     │
     └── order.place_market_order("ETH", "buy", 200)
             │
             └── SDK Exchange Client → sign + submit → ✅ filled
```

## Supported Markets

All Hyperliquid perpetual futures — ETH, BTC, SOL, and 100+ other pairs. Use `get_meta()` to list all available assets.

## Development

```bash
pip install -e ".[dev]"
pytest -v           # 12 tests
```

## Roadmap

- [ ] Stop-loss / take-profit automation
- [ ] Async support (async/await)
- [ ] WebSocket real-time price feeds
- [ ] Strategy backtesting framework

## Security

| Concern | How we handle it |
|---|---|
| Private keys | Environment variable `HYPERLIQUID_PRIVATE_KEY` — never on disk |
| Network | Default to mainnet; set `HYPERLIQUID_TESTNET=1` for testnet |
| Test first | All functions support testnet mode for safe experimentation |

## License

[MIT](LICENSE) — use it however you want.
