# Changelog

## [0.5.6] — 2026-06-05

### Added
- **Market snapshot validation**: `validate_market_snapshot` / `assert_tradeable_snapshot`
  before quoting (crossed book, wide spread, mid divergence).
- **Drawdown metrics**: `drawdown_series`, `max_drawdown`, `rank_drawdown_leaderboard`
  for equity-curve analysis.

## [0.1.0] — 2026-05-23

### Added
- Market data: quotes, orderbook, mark price, index price, funding rate
- Order execution: market orders, limit orders, cancel single/all orders
- Position management: view positions, close positions, adjust leverage
- Trade flow: end-to-end flow from quote → order → execution → monitoring
- Full Hyperliquid API client with rate limiting and error handling
- 12 tests covering API, orders, quotes, flows, and configuration
- GitHub Actions CI (Python 3.10, 3.11, 3.12)
- MIT License

[0.1.0]: https://github.com/counterfactual5/hyperliquid-autopilot/releases/tag/v0.1.0
