"""
Jesse Ops MCP Server

Operational MCP server complementing Jesse's built-in strategy-dev MCP.
Focuses on live trading, risk analysis, optimization execution, pairs trading,
and monitoring — everything the official Jesse MCP doesn't cover.

Requires Jesse v2.1.4+ with its built-in MCP server for strategy development
(backtest CRUD, candle import, strategy read/write, config, indicators).
"""

__version__ = "2.1.1"
__author__ = "Bernardo Kuri"
__all__ = ["main"]

from jesse_mcp.server import main
