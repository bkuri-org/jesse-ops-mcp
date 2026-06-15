"""
Phase 1: Backtesting Tools

Core backtesting functionality:
- backtest: Run a single backtest on a strategy
- backtest_cancel: Cancel a running backtest
- active_workers: Get list of active workers
- backtest_benchmark: Run a benchmark backtest for performance measurement
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from jesse_mcp.tools._utils import (
    async_call,
    get_client,
    require_jesse,
    tool_error_handler,
)

logger = logging.getLogger("jesse-mcp.backtesting")


def _synthesize_equity_curve(
    result: Dict[str, Any], starting_balance: float
) -> List[Dict[str, Any]]:
    """Build an equity curve from a backtest result's trade list.

    Jesse's REST API does not propagate the ``generate_equity_curve`` flag
    through to its backtest controller, so the JSON response from
    ``POST /backtest`` always contains an empty ``equity_curve`` list. This
    helper reconstructs the running balance from the trade list in the
    format expected by downstream consumers (risk_analyzer, testing_framework).

    Args:
        result: The backtest result dict, expected to contain a ``trades`` key
            with a list of trade dicts. Each trade must have ``opened_at`` (or
            ``closed_at``) timestamp in milliseconds and a ``pnl`` field (net
            profit in account currency, may be negative).
        starting_balance: Initial account balance to start the curve from.

    Returns:
        A list of dicts with ``{"date": ..., "return": pct, "equity": balance}``
        sorted by time. Matches Jesse's native equity curve format.
    """
    trades = result.get("trades") or []
    if not trades:
        return []

    from datetime import datetime, timezone as _tz

    points: List[Dict[str, Any]] = []
    running_balance = float(starting_balance)

    # Sort by opened_at if available, else closed_at
    def trade_ts(t: Dict[str, Any]) -> int:
        return int(
            t.get("closed_at")
            or t.get("opened_at")
            or t.get("exit_at")
            or t.get("entry_at")
            or 0
        )

    sorted_trades = sorted(trades, key=trade_ts)
    for trade in sorted_trades:
        # Jesse REST API uses uppercase PNL; local research uses lowercase pnl
        pnl = trade.get("pnl") or trade.get("PNL") or trade.get("profit")
        if pnl is None:
            # Some trade formats use pnl_percentage; skip if no absolute pnl
            continue
        ts = trade_ts(trade)
        if ts <= 0:
            continue
        prev_balance = running_balance
        running_balance += float(pnl)
        ret = (running_balance - prev_balance) / prev_balance if prev_balance != 0 else 0.0
        date_str = datetime.fromtimestamp(ts / 1000, tz=_tz.utc).strftime("%Y-%m-%d")
        points.append({"date": date_str, "return": round(ret, 6), "equity": round(running_balance, 2)})

    return points


def register_backtesting_tools(mcp):
    """Register backtesting tools with the MCP server"""

    @mcp.tool
    @tool_error_handler
    async def backtest(
        strategy: str,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        exchange: str = "Binance",
        starting_balance: float = 10000,
        fee: float = 0.001,
        leverage: float = 1,
        exchange_type: str = "futures",
        hyperparameters: Optional[Dict[str, Any]] = None,
        include_trades: bool = True,
        include_equity_curve: bool = True,
        include_logs: bool = False,
        fast_mode: bool = True,
        benchmark: bool = False,
        candles_pipeline_class: Optional[str] = None,
        candles_pipeline_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run a single backtest on a strategy with specified parameters.

        Returns metrics: total_return, sharpe_ratio, max_drawdown, win_rate, total_trades, etc.

        Use this to:
        - Test a single strategy version
        - Get baseline metrics for comparison
        - As first step before analyze_results, monte_carlo, or risk_report
        - For A/B testing: run backtest twice with different parameters/strategies

        Args:
            fast_mode: Enable fast mode for orders-of-magnitude speedup (default: True)
            benchmark: Enable benchmark mode for buy-and-hold comparison (default: False)
            include_trades: Include full trade list in result (default: True — needed for
                equity-curve synthesis and downstream tools like monte_carlo)
            include_equity_curve: Include synthesized equity curve in result (default: True).
                Jesse's REST API does not expose a direct equity-curve flag, so we synthesize
                the curve from the trade list. Set to False to skip the synthesis step and
                reduce response size for callers that don't need it.
            candles_pipeline_class: Custom candles pipeline class name (default: None)
            candles_pipeline_kwargs: Additional kwargs for candles pipeline (default: None)
        """
        client = get_client()
        if client is None:
            raise RuntimeError("Jesse REST client not available")

        routes = [{"strategy": strategy, "symbol": symbol, "timeframe": timeframe}]
        result = await async_call(
            client.backtest,
            routes=routes,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            starting_balance=starting_balance,
            fee=fee,
            leverage=leverage,
            exchange_type=exchange_type,
            hyperparameters=hyperparameters,
            include_trades=include_trades,
            include_equity_curve=False,  # REST API doesn't support this; we synthesize
            include_logs=include_logs,
            auto_import_candles=True,
            fast_mode=fast_mode,
            benchmark=benchmark,
            candles_pipeline_class=candles_pipeline_class,
            candles_pipeline_kwargs=candles_pipeline_kwargs,
        )

        if result.get("error") or not result.get("success", True):
            logger.error(f"Backtest failed: {result.get('error', 'Unknown error')}")
            return {
                "error": result.get("error", "Backtest failed"),
                "error_type": result.get("error_type", "BacktestError"),
                "success": False,
            }

        # Synthesize equity curve from trades if requested. Jesse's REST API
        # does not propagate the `generate_equity_curve` flag, so we compute
        # the running balance from the trade list. The curve is a list of
        # `[timestamp_ms, balance]` pairs, matching Jesse's internal format.
        if include_equity_curve:
            result["equity_curve"] = _synthesize_equity_curve(
                result, starting_balance
            )

        return result

    @mcp.tool
    @tool_error_handler
    async def backtest_cancel(
        backtest_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel a running backtest.

        Use this to stop a runaway or stuck backtest. If no backtest_id is provided,
        cancels the currently running backtest.

        Args:
            backtest_id: Optional specific backtest session ID to cancel
        """
        return await async_call(get_client().cancel_backtest, backtest_id)

    @mcp.tool
    @tool_error_handler
    async def active_workers() -> Dict[str, Any]:
        """
        Get list of active workers (running backtests, optimizations, Monte Carlo simulations).

        Use this to check what's currently running before starting new jobs,
        or to find session IDs for cancellation.
        """
        return await async_call(get_client().get_active_workers)

    @mcp.tool
    @tool_error_handler
    async def backtest_benchmark(
        symbol: str = "BTC-USDT",
        timeframe: str = "1h",
        days: int = 30,
        exchange: str = "Binance Spot",
    ) -> Dict[str, Any]:
        """
        Run a benchmark backtest to measure performance metrics.

        Measures backtest execution time and calculates candles/second performance.
        Useful for understanding how long different backtests will take.

        Args:
            symbol: Trading symbol (default: BTC-USDT)
            timeframe: Candle timeframe (default: 1h)
            days: Number of days to backtest (default: 30)
            exchange: Exchange name (default: Binance Spot)

        Returns:
            Dict with benchmark results including execution time and candles/second
        """
        import time
        from datetime import datetime

        client = get_client()
        if client is None:
            raise RuntimeError("Jesse REST client not available")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        timeframe_minutes = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        minutes = timeframe_minutes.get(timeframe, 60)
        warmup_candles = 240
        trading_candles = (days * 24 * 60) // minutes
        total_candles = trading_candles + warmup_candles

        start_time = time.time()
        routes = [
            {"strategy": "SMACrossover", "symbol": symbol, "timeframe": timeframe}
        ]
        result = await async_call(
            client.backtest,
            routes=routes,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            exchange=exchange,
            exchange_type="spot" if "Spot" in exchange else "futures",
        )
        end_time = time.time()

        execution_time = end_time - start_time

        if execution_time > 0:
            candles_per_second = total_candles / execution_time
            candles_per_minute = candles_per_second * 60
        else:
            candles_per_second = 0
            candles_per_minute = 0

        status = result.get("status", "unknown")
        is_mock = result.get("_mock_data", True)

        return {
            "benchmark_config": {
                "symbol": symbol,
                "timeframe": timeframe,
                "days": days,
                "exchange": exchange,
            },
            "performance": {
                "execution_time_seconds": round(execution_time, 3),
                "total_candles": total_candles,
                "trading_candles": trading_candles,
                "warmup_candles": warmup_candles,
                "candles_per_second": round(candles_per_second, 1),
                "candles_per_minute": round(candles_per_minute, 1),
            },
            "backtest_status": status,
            "mock_data_used": is_mock,
            "estimates": {
                "1_month_1h": f"~{round(960 / candles_per_second, 2)}s",
                "3_months_1h": f"~{round(2400 / candles_per_second, 2)}s",
                "1_year_1h": f"~{round(8880 / candles_per_second, 2)}s",
                "1_month_5m": f"~{round(8880 / candles_per_second, 2)}s",
                "1_month_1m": f"~{round(43440 / candles_per_second, 2)}s",
            },
        }
