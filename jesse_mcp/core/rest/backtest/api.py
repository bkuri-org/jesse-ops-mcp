"""
Backtest API functions for Jesse REST API client.

Contains low-level functions for submitting, polling, and retrieving results.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import requests

from jesse_mcp.core.rate_limiter import get_rate_limiter
from jesse_mcp.core.rest.backtest.helpers import estimate_max_backtest_time

logger = logging.getLogger("jesse-mcp.rest-client")

# Lazy import for httpx — only needed for async path
_httpx = None


def _get_httpx():
    global _httpx
    if _httpx is None:
        try:
            import httpx
            _httpx = httpx
        except ImportError:
            raise ImportError("httpx is required for async backtests. Install with: pip install httpx")
    return _httpx


def rate_limited_request(
    session: requests.Session,
    base_url: str,
    method: str,
    endpoint: str,
    **kwargs,
) -> Optional[requests.Response]:
    """Make a rate-limited request."""
    limiter = get_rate_limiter()
    if not limiter.acquire():
        return None
    return getattr(session, method)(f"{base_url}{endpoint}", **kwargs)


def submit_backtest(
    session: requests.Session,
    base_url: str,
    payload: dict,
    timeout: int = 300,
) -> requests.Response:
    """Submit a backtest to the API."""
    limiter = get_rate_limiter()
    if not limiter.acquire():
        raise RuntimeError("Rate limit exceeded")

    response = session.post(f"{base_url}/backtest", json=payload, timeout=timeout)
    response.raise_for_status()
    return response


def poll_backtest_result(
    session: requests.Session,
    base_url: str,
    backtest_id: str,
    poll_interval: float = 1.0,
    max_poll_time: float = 300.0,
) -> Dict[str, Any]:
    """Poll for backtest completion."""
    start_time = time.time()
    limiter = get_rate_limiter()
    last_status = None
    last_status_time = start_time
    zombie_warning_threshold = max_poll_time * 0.5

    while time.time() - start_time < max_poll_time:
        if not limiter.acquire():
            time.sleep(0.5)
            continue

        try:
            response = session.post(
                f"{base_url}/backtest/sessions",
                json={},
                timeout=10,
            )
            response.raise_for_status()
            sessions = response.json().get("sessions", [])

            for session_data in sessions:
                if session_data.get("id") == backtest_id:
                    status = session_data.get("status")
                    elapsed = time.time() - start_time

                    if status != last_status:
                        last_status = status
                        last_status_time = time.time()
                        logger.debug(
                            f"Backtest {backtest_id[:8]} status: {status} at {elapsed:.1f}s"
                        )

                    if status == "finished":
                        logger.info(
                            f"✅ Backtest {backtest_id[:8]} finished in {elapsed:.1f}s"
                        )
                        return get_backtest_session_result(
                            session, base_url, backtest_id
                        )
                    elif status in ("stopped", "cancelled"):
                        logger.info(
                            f"⏹️  Backtest {backtest_id[:8]} {status} in {elapsed:.1f}s"
                        )
                        return get_backtest_session_result(
                            session, base_url, backtest_id
                        )
                    elif status == "failed" or status == "error":
                        logger.error(
                            f"❌ Backtest {backtest_id[:8]} failed after {elapsed:.1f}s"
                        )
                        return {
                            "error": "Backtest failed",
                            "success": False,
                            "session": session_data,
                        }
                    elif status == "running":
                        if elapsed > zombie_warning_threshold:
                            logger.warning(
                                f"⚠️ Backtest {backtest_id[:8]} still running after "
                                f"{elapsed:.1f}s (max: {max_poll_time:.1f}s) - possible zombie"
                            )

            time.sleep(poll_interval)

        except Exception as e:
            logger.warning(f"Error polling backtest status: {e}")
            time.sleep(poll_interval)

    elapsed = time.time() - start_time
    logger.error(
        f"❌ Backtest {backtest_id[:8]} timed out after {elapsed:.1f}s - "
        f"likely zombie process (max allowed: {max_poll_time:.1f}s)"
    )
    return {
        "error": f"Backtest timed out after {elapsed:.1f}s (zombie detected)",
        "success": False,
        "zombie": True,
        "max_allowed_time": max_poll_time,
    }


def get_backtest_session_result(
    session: requests.Session,
    base_url: str,
    backtest_id: str,
) -> Dict[str, Any]:
    """Get full backtest result from session."""
    try:
        response = session.post(
            f"{base_url}/backtest/sessions/{backtest_id}",
            json={},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        session_data = data.get("session", {})
        status = session_data.get("status")
        metrics = session_data.get("metrics", {})

        if not metrics:
            logger.warning(f"Empty metrics in backtest result")
            return {
                "error": "Empty metrics in result",
                "success": False,
                "session": session_data,
            }

        result = {
            "id": backtest_id,
            "status": status,
            "total_return": metrics.get("net_profit_percentage"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "win_rate": metrics.get("win_rate"),
            "total_trades": metrics.get("total"),
            "total_winning_trades": metrics.get("total_winning_trades"),
            "total_losing_trades": metrics.get("total_losing_trades"),
            "starting_balance": metrics.get("starting_balance"),
            "finishing_balance": metrics.get("finishing_balance"),
            "net_profit": metrics.get("net_profit"),
            "annual_return": metrics.get("annual_return"),
            "expectancy": metrics.get("expectancy"),
            "average_win": metrics.get("average_win"),
            "average_loss": metrics.get("average_loss"),
            "largest_winning_trade": metrics.get("largest_winning_trade"),
            "largest_losing_trade": metrics.get("largest_losing_trade"),
            "max_underwater_period": metrics.get("max_underwater_period"),
            "win_rate_long": metrics.get("win_rate_long"),
            "win_rate_short": metrics.get("win_rate_short"),
            "winning_streak": metrics.get("winning_streak"),
            "losing_streak": metrics.get("losing_streak"),
            "equity_curve": session_data.get("equity_curve"),
            "trades": session_data.get("trades"),
            "execution_duration": session_data.get("execution_duration"),
            "strategy_codes": session_data.get("strategy_codes"),
            "success": True,
        }

        logger.info(
            f"✅ Retrieved backtest result: return={_format_total_return(result.get('total_return'))}, "
            f"sharpe={result.get('sharpe_ratio', 'N/A')}"
        )
        return result

    except Exception as e:
        import traceback
        logger.error(f"❌ Failed to get backtest result: {e}\n{traceback.format_exc()}")
        return {"error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc(), "success": False}


def cancel_backtest(
    session: requests.Session,
    base_url: str,
    backtest_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancel a running backtest."""
    try:
        payload = {}
        if backtest_id:
            payload["id"] = backtest_id

        response = session.post(
            f"{base_url}/backtest/cancel",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

        logger.info(f"Backtest cancel response: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to cancel backtest: {e}")
        return {"error": str(e), "success": False}


def execute_backtest(
    session: requests.Session,
    base_url: str,
    payload: dict,
    timeout: int = 300,
    poll_interval: float = 1.0,
    max_poll_time: Optional[float] = None,
) -> Dict[str, Any]:
    """Submit a backtest and poll for results."""
    limiter = get_rate_limiter()
    if not limiter.acquire():
        return {"error": "Rate limit exceeded", "success": False}

    backtest_id = payload.get("id")
    if not backtest_id:
        return {"error": "Missing backtest ID in payload", "success": False}

    if max_poll_time is None:
        start_date = payload.get("start_date", "")
        end_date = payload.get("finish_date", payload.get("end_date", ""))
        timeframe = "1h"
        if payload.get("routes"):
            timeframe = payload["routes"][0].get("timeframe", "1h")
        max_poll_time = estimate_max_backtest_time(start_date, end_date, timeframe)

    response = session.post(f"{base_url}/backtest", json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json()

    if "total_return" in result or "metrics" in result:
        logger.info(f"✅ Backtest returned immediate result")
        return result

    if response.status_code == 202 or result.get("message", "").startswith("Started"):
        logger.info(f"⏳ Backtest {backtest_id[:8]} started, polling for completion...")
        return poll_backtest_result(
            session, base_url, backtest_id, poll_interval, max_poll_time
        )

    return result


def _format_total_return(value):
    """Format total_return for logging, guarding against null/non-numeric."""
    return f"{float(value):.2f}%" if isinstance(value, (int, float)) else "N/A"


# ---------------------------------------------------------------------------
# Async backtest functions (httpx-based)
# ---------------------------------------------------------------------------

async def async_poll_backtest_result(
    client,
    base_url: str,
    backtest_id: str,
    poll_interval: float = 1.0,
    max_poll_time: float = 300.0,
    auth_token: str = "",
) -> Dict[str, Any]:
    """Poll for backtest completion using async HTTP."""
    start_time = time.time()
    limiter = get_rate_limiter()
    last_status = None
    zombie_warning_threshold = max_poll_time * 0.5
    headers = {}
    if auth_token:
        headers["authorization"] = auth_token

    while time.time() - start_time < max_poll_time:
        if not limiter.acquire():
            await asyncio.sleep(0.5)
            continue

        try:
            response = await client.post(
                f"{base_url}/backtest/sessions",
                json={},
                timeout=10,
                headers=headers,
            )
            response.raise_for_status()
            sessions = response.json().get("sessions", [])

            for session_data in sessions:
                if session_data.get("id") == backtest_id:
                    status = session_data.get("status")
                    elapsed = time.time() - start_time

                    if status != last_status:
                        last_status = status
                        logger.debug(
                            f"Backtest {backtest_id[:8]} status: {status} at {elapsed:.1f}s"
                        )

                    if status == "finished":
                        logger.info(
                            f"✅ Backtest {backtest_id[:8]} finished in {elapsed:.1f}s"
                        )
                        return await async_get_backtest_session_result(
                            client, base_url, backtest_id, auth_token
                        )
                    elif status in ("stopped", "cancelled"):
                        logger.info(
                            f"⏹️  Backtest {backtest_id[:8]} {status} in {elapsed:.1f}s"
                        )
                        return await async_get_backtest_session_result(
                            client, base_url, backtest_id, auth_token
                        )
                    elif status == "failed" or status == "error":
                        logger.error(
                            f"❌ Backtest {backtest_id[:8]} failed after {elapsed:.1f}s"
                        )
                        return {
                            "error": "Backtest failed",
                            "success": False,
                            "session": session_data,
                        }
                    elif status == "running":
                        if elapsed > zombie_warning_threshold:
                            logger.warning(
                                f"⚠️ Backtest {backtest_id[:8]} still running after "
                                f"{elapsed:.1f}s (max: {max_poll_time:.1f}s) - possible zombie"
                            )

            await asyncio.sleep(poll_interval)

        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code is not None and 400 <= status_code < 500:
                logger.error(f"Polling failed with HTTP {status_code}: {e}")
                return {
                    "error": f"Polling failed with HTTP {status_code}",
                    "success": False,
                }
            logger.warning(f"Error polling backtest status: {e}")
            await asyncio.sleep(poll_interval)

    elapsed = time.time() - start_time
    logger.error(
        f"❌ Backtest {backtest_id[:8]} timed out after {elapsed:.1f}s - "
        f"likely zombie process (max allowed: {max_poll_time:.1f}s)"
    )
    return {
        "error": f"Backtest timed out after {elapsed:.1f}s (zombie detected)",
        "success": False,
        "zombie": True,
        "max_allowed_time": max_poll_time,
    }


async def async_get_backtest_session_result(
    client,
    base_url: str,
    backtest_id: str,
    auth_token: str = "",
) -> Dict[str, Any]:
    """Get full backtest result from session using async HTTP."""
    headers = {}
    if auth_token:
        headers["authorization"] = auth_token

    try:
        response = await client.post(
            f"{base_url}/backtest/sessions/{backtest_id}",
            json={},
            timeout=30,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        session_data = data.get("session", {})
        status = session_data.get("status")
        metrics = session_data.get("metrics", {})

        if not metrics:
            logger.warning(f"Empty metrics in backtest result")
            return {
                "error": "Empty metrics in result",
                "success": False,
                "session": session_data,
            }

        result = {
            "id": backtest_id,
            "status": status,
            "total_return": metrics.get("net_profit_percentage"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "win_rate": metrics.get("win_rate"),
            "total_trades": metrics.get("total"),
            "total_winning_trades": metrics.get("total_winning_trades"),
            "total_losing_trades": metrics.get("total_losing_trades"),
            "starting_balance": metrics.get("starting_balance"),
            "finishing_balance": metrics.get("finishing_balance"),
            "net_profit": metrics.get("net_profit"),
            "annual_return": metrics.get("annual_return"),
            "expectancy": metrics.get("expectancy"),
            "average_win": metrics.get("average_win"),
            "average_loss": metrics.get("average_loss"),
            "largest_winning_trade": metrics.get("largest_winning_trade"),
            "largest_losing_trade": metrics.get("largest_losing_trade"),
            "max_underwater_period": metrics.get("max_underwater_period"),
            "win_rate_long": metrics.get("win_rate_long"),
            "win_rate_short": metrics.get("win_rate_short"),
            "winning_streak": metrics.get("winning_streak"),
            "losing_streak": metrics.get("losing_streak"),
            "equity_curve": session_data.get("equity_curve"),
            "trades": session_data.get("trades"),
            "execution_duration": session_data.get("execution_duration"),
            "strategy_codes": session_data.get("strategy_codes"),
            "success": True,
        }

        logger.info(
            f"✅ Retrieved backtest result: return={_format_total_return(result.get('total_return'))}, "
            f"sharpe={result.get('sharpe_ratio', 'N/A')}"
        )
        return result

    except Exception as e:
        logger.error(f"❌ Failed to get backtest result: {e}")
        return {"error": str(e), "success": False}


async def async_execute_backtest(
    client,
    base_url: str,
    payload: dict,
    auth_token: str = "",
    timeout: int = 300,
    poll_interval: float = 1.0,
    max_poll_time: Optional[float] = None,
) -> Dict[str, Any]:
    """Submit a backtest and poll for results using async HTTP."""
    limiter = get_rate_limiter()
    if not limiter.acquire():
        return {"error": "Rate limit exceeded", "success": False}

    backtest_id = payload.get("id")
    if not backtest_id:
        return {"error": "Missing backtest ID in payload", "success": False}

    if max_poll_time is None:
        start_date = payload.get("start_date", "")
        end_date = payload.get("finish_date", payload.get("end_date", ""))
        timeframe = "1h"
        if payload.get("routes"):
            timeframe = payload["routes"][0].get("timeframe", "1h")
        max_poll_time = estimate_max_backtest_time(start_date, end_date, timeframe)

    headers = {}
    if auth_token:
        headers["authorization"] = auth_token

    response = await client.post(
        f"{base_url}/backtest", json=payload, timeout=timeout, headers=headers
    )
    response.raise_for_status()
    result = response.json()

    if "total_return" in result or "metrics" in result:
        logger.info(f"✅ Backtest returned immediate result")
        return result

    if response.status_code == 202 or result.get("message", "").startswith("Started"):
        logger.info(f"⏳ Backtest {backtest_id[:8]} started, polling for completion...")
        return await async_poll_backtest_result(
            client, base_url, backtest_id, poll_interval, max_poll_time, auth_token
        )

    return result
