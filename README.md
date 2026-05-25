# Jesse Ops MCP Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An **operational** MCP (Model Context Protocol) server for [Jesse](https://jesse.trade) — covering live trading, risk analysis, optimization execution, pairs trading, and monitoring. Designed to **complement** Jesse's built-in MCP server (v2.1.4+), which handles strategy development (backtest CRUD, candle import, strategy read/write, config, indicators).

## Why This Exists

Jesse v2.1.4 ships a built-in MCP server for **strategy development workflows** — creating strategies, running backtests, importing candles, browsing indicators. That covers the coding side.

**jesse-ops-mcp** covers everything else — the **operational side** that the official MCP doesn't touch:

| Domain | Official MCP | jesse-ops-mcp |
|--------|:------------:|:-------------:|
| Strategy CRUD | ✅ | — |
| Backtest drafts | ✅ | — |
| Candle import | ✅ | — |
| Config / indicators | ✅ | — |
| **Live Trading** | — | ✅ |
| **Paper Trading** | — | ✅ |
| **Risk Analysis** | — | ✅ |
| **Monte Carlo** | — | ✅ |
| **Optimization** | — | ✅ |
| **Walk-Forward** | — | ✅ |
| **Pairs Trading** | — | ✅ |
| **Community Browse** | — | ✅ |

## Installation

```bash
pip install jesse-ops-mcp
```

### From Source

```bash
git clone https://github.com/bkuri-org/jesse-ops-mcp.git
cd jesse-ops-mcp
pip install -e .
```

## Usage

```bash
# stdio transport (default, for MCP clients)
jesse-ops-mcp

# HTTP transport (for remote access)
jesse-ops-mcp --transport http --port 8100

# Show help
jesse-ops-mcp --help
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `JESSE_URL` | Jesse REST API URL | `http://server2:9100` |
| `JESSE_PASSWORD` | Jesse UI password | (required) |
| `JESSE_API_TOKEN` | Pre-generated API token | (alternative to password) |
| `JESSE_TRADE_API_KEY` | jesse.trade community API Bearer token | (optional) |

## Available Tools

### Live Trading (17 tools)

Full live and paper trading lifecycle:

| Tool | Description |
|------|-------------|
| `live_start_paper_trading` | Start paper trading session (safe) |
| `live_start_live_trading` | Start live trading (⚠️ requires risk acknowledgment) |
| `live_cancel_session` | Cancel running session |
| `live_get_sessions` | List active sessions |
| `live_get_status` | Current session status |
| `live_get_orders` | Open orders |
| `live_get_equity_curve` | Real-time equity curve |
| `live_get_logs` | Session logs |
| `live_check_plugin` | Verify Jesse live plugin installed |
| `paper_start` | Start standalone paper session |
| `paper_stop` | Stop paper session |
| `paper_status` | Paper session status |
| `paper_get_trades` | Paper trade history |
| `paper_get_equity` | Paper equity curve |
| `paper_get_metrics` | Paper session metrics |
| `paper_list_sessions` | List all paper sessions |
| `paper_update_session` | Update paper session config |

**Safety**: Max position 10%, daily loss 5%, drawdown 15%, auto-stop on limit.

### Optimization (6 tools)

| Tool | Description |
|------|-------------|
| `optimize` | Optimize hyperparameters using Optuna |
| `optimization_cancel` | Cancel running optimization |
| `monte_carlo_cancel` | Cancel Monte Carlo simulation |
| `walk_forward` | Walk-forward analysis for overfitting detection |
| `backtest_batch` | Run concurrent multi-asset backtests |
| `analyze_results` | Extract insights from optimization results |

### Risk Analysis (7 tools)

| Tool | Description |
|------|-------------|
| `monte_carlo` | Monte Carlo simulations for risk assessment |
| `native_monte_carlo` | Jesse-native Monte Carlo via REST API |
| `var_calculation` | Value at Risk (historical, parametric, Monte Carlo) |
| `stress_test` | Test under extreme market scenarios |
| `risk_report` | Comprehensive risk assessment report |
| `plot_significance_test` | Statistical significance visualization |
| `rule_significance_test` | Rule-based significance testing |

### Pairs Trading (4 tools)

| Tool | Description |
|------|-------------|
| `correlation_matrix` | Cross-asset correlation analysis |
| `pairs_backtest` | Backtest pairs trading strategies |
| `factor_analysis` | Decompose returns into systematic factors |
| `regime_detector` | Identify market regimes and transitions |

### Community (5 tools)

Browse [jesse.trade](https://jesse.trade) community strategies:

| Tool | Description |
|------|-------------|
| `list_periods` | Available backtest periods on jesse.trade |
| `browse_community_strategies` | Browse strategies sorted by performance |
| `get_strategy_metrics` | Detailed metrics for a specific strategy |
| `get_strategy_code` | Full Python source code for a strategy |
| `compare_community_strategies` | Side-by-side comparison of multiple strategies |

### Job Management (6 tools)

| Tool | Description |
|------|-------------|
| `strategy_create_status` | Poll async strategy creation progress |
| `strategy_create_cancel` | Cancel async creation job |
| `jobs_list` | List all active jobs |
| `rate_limit_status` | Check rate limiter state |
| `cache_stats` | Cache statistics |
| `cache_clear` | Clear cached data |

### Agent Tools (23 tools)

Specialized tools for autonomous trading workflows — portfolio analysis, leverage assessment, hedging recommendations, drawdown recovery, regime-aware backtesting, significance validation, and more.

## Architecture

```
LLM Agent ←→ MCP Protocol ←→ jesse-ops-mcp ←→ Jesse REST API (localhost:9000)
                                    ↓
                            Mock Fallbacks (when Jesse unavailable)
```

Complementary to the **built-in Jesse MCP** which runs inside the Jesse process:

```
Coding Agent ←→ Official Jesse MCP (built-in) ←→ Jesse internals
                                        ↕
Ops Agent ←→ jesse-ops-mcp ←→ Jesse REST API
```

## Testing

```bash
pip install jesse-ops-mcp[dev]
pytest -v
```

## Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastmcp | >=0.3.0 | MCP server framework |
| numpy | >=1.24.0 | Numerical computations |
| pandas | >=2.0.0 | Data manipulation |
| scipy | >=1.10.0 | Statistical functions |
| scikit-learn | >=1.3.0 | ML utilities |

## License

MIT License - see [LICENSE](LICENSE) file for details.
