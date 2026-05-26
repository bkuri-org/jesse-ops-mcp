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
        """Generate Monte Carlo simulations for comprehensive risk analysis"""
        ra = require_risk_analyzer()
        return await ra.monte_carlo(
            backtest_result=backtest_result,
            simulations=simulations,
            confidence_levels=confidence_levels or [],
            resample_method=resample_method,
            block_size=block_size,
            include_drawdowns=include_drawdowns,
            include_returns=include_returns,
        )

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
