"""
Strategy Job Management, Rate Limiting & Caching Tools

Async job tracking for strategy creation, rate limiter status,
and cache management utilities.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jesse_mcp.core.strategy_validation.metadata import (
    get_or_create_metadata,
    save_metadata,
)
from jesse_mcp.tools._utils import (
    get_strategies_path,
    tool_error_handler,
)

logger = logging.getLogger("jesse-mcp.strategy")


def _strategy_create_impl(
    name: str,
    description: str,
    indicators: Optional[List[str]] = None,
    strategy_type: str = "trend_following",
    risk_per_trade: float = 0.02,
    timeframe: str = "1h",
    max_iterations: int = 5,
    overwrite: bool = False,
    skip_backtest: bool = False,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Internal implementation for strategy creation with iterative refinement.
    """
    from jesse_mcp.core.job_manager import JobStatus, get_job_manager
    from jesse_mcp.core.strategy_builder import StrategySpec, get_strategy_builder
    from jesse_mcp.core.strategy_validator import get_validator
    import os

    try:
        strategies_path = get_strategies_path()

        strategy_dir = os.path.join(strategies_path, name)
        strategy_file = os.path.join(strategy_dir, "__init__.py")

        if os.path.exists(strategy_dir) and not overwrite:
            return {
                "error": f"Strategy '{name}' already exists. Use overwrite=True to replace.",
                "status": "failed",
                "name": name,
            }

        validator = get_validator()
        builder = get_strategy_builder(validator)

        metadata = get_or_create_metadata(name, strategies_path)

        spec = StrategySpec(
            name=name,
            description=description,
            strategy_type=strategy_type,
            indicators=indicators or [],
            risk_per_trade=risk_per_trade,
            timeframe=timeframe,
        )

        if progress_callback:
            progress_callback(0.1, "Generating initial strategy code", 0)

        code = builder.generate_initial(spec)

        def internal_progress(pct: float, step: str, iteration: int):
            if progress_callback:
                progress_callback(0.1 + (pct * 0.8), step, iteration)

        os.makedirs(strategy_dir, exist_ok=True)
        with open(strategy_file, "w") as f:
            f.write(code)
        logger.info(f"✅ Strategy saved: {strategy_file}")

        final_code, history, success = builder.refinement_loop(
            code,
            spec,
            max_iter=max_iterations,
            skip_backtest=skip_backtest,
            progress_callback=internal_progress,
        )

        for h in history:
            dry_run = h.get("dry_run", {})
            if dry_run and not dry_run.get("skipped"):
                passed = dry_run.get("passed", False)
                metadata.record_test(passed)
                save_metadata(metadata, strategies_path)

        if metadata.should_certify():
            metadata.certify()
            save_metadata(metadata, strategies_path)

        if progress_callback:
            progress_callback(0.95, "Updating strategy", max_iterations)

        if final_code != code:
            with open(strategy_file, "w") as f:
                f.write(final_code)
            logger.info(f"✅ Strategy updated: {strategy_file}")

        return {
            "status": "created" if success else "validation_failed",
            "name": name,
            "version": metadata.version,
            "test_count": metadata.test_count,
            "test_pass_count": metadata.test_pass_count,
            "certified": metadata.certified_at is not None,
            "iterations": len(history),
            "validation_history": [
                {
                    "iteration": h["iteration"],
                    "passed": h["result"].get("passed", False),
                }
                for h in history
            ],
            "path": strategy_file if success else None,
            "code": final_code,
            "ready_for_backtest": success,
        }

    except Exception as e:
        logger.error(f"Strategy creation failed: {e}")
        return {"error": str(e), "error_type": type(e).__name__, "status": "failed"}


def register_strategy_tools(mcp):
    """Register strategy creation and management tools with the MCP server."""

    @mcp.tool(name="strategy_create_status")
    @tool_error_handler
    def strategy_create_status(job_id: str) -> Dict[str, Any]:
        """
        Poll async job progress for strategy creation.

        Args:
            job_id: Job identifier from strategy_create

        Returns:
            Dict with job_id, status, progress_percent, current_step,
            iterations_completed, iterations_total, elapsed_seconds, result (when complete)
        """
        from jesse_mcp.core.job_manager import get_job_manager

        job_manager = get_job_manager()
        job = job_manager.get_job(job_id)

        if not job:
            return {"error": f"Job not found: {job_id}", "job_id": job_id}

        elapsed = None
        if job.started_at:
            elapsed = (datetime.now(timezone.utc) - job.started_at).total_seconds()

        result = {
            "job_id": job_id,
            "status": job.status.value,
            "progress_percent": job.progress_percent,
            "current_step": job.current_step,
            "iterations_completed": job.iterations_completed,
            "iterations_total": job.iterations_total,
            "elapsed_seconds": elapsed,
        }

        if job.status.value in ("complete", "failed", "cancelled"):
            result["result"] = job.result
            if job.error:
                result["error"] = job.error

        return result

    @mcp.tool(name="strategy_create_cancel")
    @tool_error_handler
    def strategy_create_cancel(job_id: str) -> Dict[str, Any]:
        """
        Cancel async strategy creation job.

        Args:
            job_id: Job identifier to cancel

        Returns:
            Dict with status, job_id
        """
        from jesse_mcp.core.job_manager import get_job_manager

        job_manager = get_job_manager()
        cancelled = job_manager.cancel_job(job_id)

        if cancelled:
            return {"status": "cancelled", "job_id": job_id}
        else:
            return {
                "status": "not_cancelled",
                "job_id": job_id,
                "reason": "Job not found or already complete",
            }

    @mcp.tool(name="jobs_list")
    @tool_error_handler
    def jobs_list(job_type: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        List recent jobs.

        Args:
            job_type: Filter by job type (optional)
            limit: Maximum number of jobs to return (default: 50)

        Returns:
            Dict with list of jobs containing id, type, status, progress, current_step, started_at
        """
        from jesse_mcp.core.job_manager import get_job_manager

        job_manager = get_job_manager()
        jobs = job_manager.list_jobs(job_type=job_type, limit=limit)

        return {
            "jobs": [
                {
                    "id": job.id,
                    "type": job.type,
                    "status": job.status.value,
                    "progress": job.progress_percent,
                    "current_step": job.current_step,
                    "started_at": (
                        job.started_at.isoformat() if job.started_at else None
                    ),
                }
                for job in jobs
            ],
            "count": len(jobs),
        }

    @mcp.tool(name="rate_limit_status")
    @tool_error_handler
    def rate_limit_status() -> Dict[str, Any]:
        """
        Get current rate limiter status for Jesse API calls.

        Returns:
            Dict with rate limit configuration and statistics:
            - enabled: Whether rate limiting is active
            - rate_per_second: Configured requests per second
            - available_tokens: Current tokens available
            - wait_mode: Whether to wait or reject when limited
            - stats: Total requests, waits, rejections, wait time
        """
        from jesse_mcp.core.rate_limiter import get_rate_limiter

        limiter = get_rate_limiter()
        return limiter.get_status()

    @mcp.tool(name="cache_stats")
    @tool_error_handler
    def cache_stats() -> Dict[str, Any]:
        """
        Get cache statistics including hit/miss ratio and cache sizes.

        Returns:
            Dict with cache status, hit rates, and sizes for all caches
        """
        from jesse_mcp.core.cache import get_all_stats

        return get_all_stats()

    @mcp.tool(name="cache_clear")
    @tool_error_handler
    def cache_clear(cache_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Clear cache(s) to free memory or force fresh data.

        Args:
            cache_name: Specific cache to clear (strategy_list, backtest).
                       If None, clears all caches.

        Returns:
            Dict with number of entries cleared per cache
        """
        from jesse_mcp.core.cache import clear_all_caches, clear_cache

        if cache_name:
            count = clear_cache(cache_name)
            return {"cleared": {cache_name: count}}
        else:
            return {"cleared": clear_all_caches()}
