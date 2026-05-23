# Contributing to hyperliquid-autopilot

## Setup

```bash
git clone https://github.com/counterfactual5/hyperliquid-autopilot.git
cd hyperliquid-autopilot
uv pip install -e ".[dev]"
```

## Running Tests

```bash
uv run pytest tests/ -v
```

12 tests covering API client, order building, quote logic, trade flow, and configuration.

## Code Style

- Python 3.10+ compatible
- 120-char line length
- Public functions have docstrings
- Use defensive `.get()` access for API responses

## Project Structure

```
src/hyperliquid_autopilot/
├── common.py       # API client, HTTP helpers, configuration
├── quote.py        # Market quotes, orderbook, price formatting
├── order.py        # Order construction and validation
└── flow.py         # End-to-end trade flow orchestration
```

## Pull Requests

1. Fork → feature branch → changes + tests → PR to `master`
2. Keep PRs focused — one concern per PR
