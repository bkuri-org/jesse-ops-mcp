"""
Phase 4: Risk Analysis Tools

Monte Carlo simulation, Value at Risk, stress testing, risk reporting,
and significance test visualization.

NOTE (v2.1.0): native_monte_carlo and rule_significance_test have been removed.
These are now provided by Jesse's built-in MCP (v2.2.0+) at :9002:
  - create_monte_carlo_draft / run_monte_carlo / get_monte_carlo_session
  - create_significance_test_draft / run_significance_test / get_significance_test_session
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from jesse_mcp.tools._utils import (
    async_call,
    get_client,
    require_risk_analyzer,
    tool_error_handler,
)

logger = logging.getLogger("jesse-mcp.risk")


def register_risk_tools(mcp):
    """Register risk analysis tools with the MCP server."""

    @mcp.tool
    @tool_error_handler
    async def monte_carlo(
        backtest_result: Dict[str, Any],
        simulations: int = 10000,
        confidence_levels: Optional[List[float]] = None,
        resample_method: str = "bootstrap",
        block_size: int = 20,
        include_drawdowns: bool = True,
        include_returns: bool = True,
    ) -> Dict[str, Any]:
        """Generate Monte Carlo simulations for comprehensive risk analysis

        Uses the equity curve from a prior backtest() call (which
        synthesizes the curve from the trade list).  If the equity curve
        is missing or too short, returns a descriptive error instead of
        crashing.

        The resample_method controls how returns are shuffled:
        - "bootstrap": simple random resampling (default)
        - "block_bootstrap": preserve local order with blocks
        - "stationary_bootstrap": random-length blocks
        """
        import time as _time

        _start = _time.time()
        if confidence_levels is None:
            confidence_levels = [0.95, 0.99]

        raw_curve = backtest_result.get("equity_curve")
        if not raw_curve or len(raw_curve) < 2:
            return {
                "error": (
                    "Equity curve not available or too short. "
                    "Ensure the backtest was run with include_equity_curve=True "
                    "(default) and produced trades."
                ),
                "simulations": 0,
            }

        # Normalise to [{"return": float, ...}] list
        returns = _extract_returns(raw_curve)
        if len(returns) < 2:
            return {
                "error": f"Only {len(returns)} return points after normalisation; need >= 2.",
                "simulations": 0,
            }

        starting_balance = backtest_result.get(
            "starting_balance",
            raw_curve[0].get("equity", 10000) if isinstance(raw_curve[0], dict) else 10000,
        )

        # Run simulations
        final_values: List[float] = []
        max_drawdowns: List[float] = []
        total_returns: List[float] = []

        for _ in range(simulations):
            if resample_method == "block_bootstrap" and block_size > 1:
                sampled = _block_bootstrap(returns, block_size)
            elif resample_method == "stationary_bootstrap":
                sampled = _stationary_bootstrap(returns)
            else:
                sampled = list(np.random.choice(returns, size=len(returns), replace=True))

            path_value = starting_balance
            path_peak = starting_balance
            path_dd = 0.0
            for ret in sampled:
                path_value *= 1 + ret
                path_peak = max(path_peak, path_value)
                path_dd = max(path_dd, (path_peak - path_value) / path_peak if path_peak > 0 else 0)

            final_values.append(path_value)
            max_drawdowns.append(path_dd)
            total_returns.append((path_value - starting_balance) / starting_balance)

        # Statistics
        fv_arr = np.array(final_values)
        dd_arr = np.array(max_drawdowns)
        tr_arr = np.array(total_returns)

        result: Dict[str, Any] = {
            "simulations": simulations,
            "resample_method": resample_method,
            "starting_balance": starting_balance,
            "return_points": len(returns),
            "final_value": {
                "mean": round(float(np.mean(fv_arr)), 2),
                "std": round(float(np.std(fv_arr)), 2),
                "min": round(float(np.min(fv_arr)), 2),
                "max": round(float(np.max(fv_arr)), 2),
                "median": round(float(np.median(fv_arr)), 2),
            },
            "probability_of_profit": round(float(np.mean(fv_arr > starting_balance)), 4),
        }

        if include_drawdowns:
            result["max_drawdown"] = {
                "mean": round(float(np.mean(dd_arr)), 4),
                "std": round(float(np.std(dd_arr)), 4),
                "worst": round(float(np.max(dd_arr)), 4),
                "p95": round(float(np.percentile(dd_arr, 95)), 4),
            }

        if include_returns:
            result["total_return"] = {
                "mean": round(float(np.mean(tr_arr)), 4),
                "std": round(float(np.std(tr_arr)), 4),
                "min": round(float(np.min(tr_arr)), 4),
                "max": round(float(np.max(tr_arr)), 4),
            }

        # Confidence intervals on final value
        ci: Dict[str, Dict[str, float]] = {}
        for level in confidence_levels:
            lo = round(float(np.percentile(fv_arr, (1 - level) * 100)), 2)
            hi = round(float(np.percentile(fv_arr, level * 100)), 2)
            ci[f"{level * 100:.0f}%"] = {"lower": lo, "upper": hi}
        result["confidence_intervals"] = ci

        result["execution_time"] = round(_time.time() - _start, 2)
        return result

    @mcp.tool
    @tool_error_handler
    async def var_calculation(
        backtest_result: Dict[str, Any],
        confidence_levels: Optional[List[float]] = None,
        time_horizons: Optional[List[int]] = None,
        method: str = "all",
        monte_carlo_sims: int = 10000,
    ) -> Dict[str, Any]:
        """Calculate Value at Risk using multiple methods"""
        ra = require_risk_analyzer()
        return await ra.var_calculation(
            backtest_result=backtest_result,
            confidence_levels=confidence_levels or [],
            time_horizons=time_horizons or [],
            method=method,
            monte_carlo_sims=monte_carlo_sims,
        )

    @mcp.tool
    @tool_error_handler
    async def stress_test(
        backtest_result: Dict[str, Any],
        scenarios: Optional[List[str]] = None,
        include_custom_scenarios: bool = False,
    ) -> Dict[str, Any]:
        """Test strategy performance under extreme market scenarios"""
        ra = require_risk_analyzer()
        return await ra.stress_test(
            backtest_result=backtest_result,
            scenarios=scenarios,
            custom_scenarios=include_custom_scenarios,
        )

    @mcp.tool(name="risk_report")
    @tool_error_handler
    async def risk_report(
        backtest_result: Dict[str, Any],
        include_monte_carlo: bool = True,
        include_var_analysis: bool = True,
        include_stress_test: bool = True,
        monte_carlo_sims: int = 5000,
        report_format: str = "summary",
    ) -> Dict[str, Any]:
        """Generate comprehensive risk assessment and recommendations"""
        ra = require_risk_analyzer()
        return await ra.risk_report(
            backtest_result=backtest_result,
            include_monte_carlo=include_monte_carlo,
            include_var_analysis=include_var_analysis,
            include_stress_test=include_stress_test,
            monte_carlo_sims=monte_carlo_sims,
            report_format=report_format,
        )

    @mcp.tool
    @tool_error_handler
    def plot_significance_test(
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
        n_bootstrap: int = 1000,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate bootstrap significance test histogram as PNG chart.

        Creates a histogram of the bootstrap sampling distribution with the
        observed mean annotated, saved as a PNG file. Requires local Jesse installation.

        Use alongside Jesse's built-in significance test tools for visual analysis
        of whether a strategy's performance is statistically significant.

        Args:
            strategy: Strategy name to test
            symbol: Trading pair (e.g., "BTC-USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h")
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD
            exchange: Exchange name (default: Binance)
            n_bootstrap: Number of bootstrap samples (default: 1000)
            output_path: Optional custom path for the PNG file
        """
        from jesse_mcp.tools._utils import require_jesse

        return require_jesse().plot_significance_test(
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            starting_balance=starting_balance,
            fee=fee,
            leverage=leverage,
            exchange_type=exchange_type,
            hyperparameters=hyperparameters,
            n_bootstrap=n_bootstrap,
            output_path=output_path,
        )


# ---------------------------------------------------------------------------
# Module-level helpers for monte_carlo
# ---------------------------------------------------------------------------

def _extract_returns(raw_curve: List[Any]) -> List[float]:
    """Normalise various equity-curve formats into a plain returns list.

    Handles:
    - [{"return": x, ...}, ...]  (already computed)
    - [{"equity": x, ...}, ...]  (convert to returns)
    - [{"value": x, "time": t}, ...]  (Jesse native format)
    - [{"data": [...]}]  (Jesse nested format)
    """
    if not raw_curve:
        return []

    first = raw_curve[0]

    # Jesse nested wrapper
    if isinstance(first, dict) and "data" in first and isinstance(first["data"], list):
        inner = first["data"]
        if inner:
            return _extract_returns(inner)
        return []

    # Already has "return" field
    if isinstance(first, dict) and "return" in first:
        return [float(p["return"]) for p in raw_curve if "return" in p]

    # Has "value" or "equity" field
    if isinstance(first, dict) and ("value" in first or "equity" in first):
        returns: List[float] = []
        prev = 0.0
        for i, p in enumerate(raw_curve):
            val = float(p.get("value", p.get("equity", 0)))
            if i == 0:
                returns.append(0.0)
            else:
                returns.append((val - prev) / prev if prev != 0 else 0.0)
            prev = val
        return returns

    return []


def _block_bootstrap(returns: List[float], block_size: int) -> List[float]:
    """Block bootstrap: sample blocks of size `block_size` to preserve local order."""
    n = len(returns)
    sampled: List[float] = []
    while len(sampled) < n:
        start = np.random.randint(0, n - block_size + 1)
        sampled.extend(returns[start : start + block_size])
    return sampled[:n]


def _stationary_bootstrap(returns: List[float]) -> List[float]:
    """Stationary bootstrap: random block sizes with geometric distribution."""
    import random

    n = len(returns)
    sampled: List[float] = []
    p = 1.0 / 10  # average block size = 10
    while len(sampled) < n:
        start = np.random.randint(0, n)
        block_len = 1
        while random.random() < 1 - p:
            block_len += 1
        sampled.extend(returns[start : start + block_len])
    return sampled[:n]
