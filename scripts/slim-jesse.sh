#!/bin/bash
set -euo pipefail

# === CONFIGURATION ===

SCRIPT_VERSION="1.0.0"
MARKER_FILE=".jesse-mcp-patched"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# === ARGUMENTS ===

VENV_PATH="${1:-}"

if [[ -z "$VENV_PATH" ]]; then
    VENV_PATH=$(python -c "import sys, os; print(os.path.dirname(sys.executable))")
    info "Auto-detected venv: $VENV_PATH"
fi

if [[ ! -d "$VENV_PATH" ]]; then
    error "Venv not found: $VENV_PATH"
    exit 1
fi

PYTHON="$VENV_PATH/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    error "Python not found at $PYTHON"
    exit 1
fi

# === FIND JESSE ===

JESSE_DIR=""

init_py=$(find "$VENV_PATH/lib" -path "*/jesse/__init__.py" 2>/dev/null | head -1)
if [[ -n "$init_py" ]]; then
    JESSE_DIR=$(dirname "$init_py")
fi

if [[ -z "$JESSE_DIR" ]]; then
    jesse_check=$("$PYTHON" -c "import jesse, os; print(os.path.dirname(jesse.__file__))" 2>/dev/null || true)
    if [[ -n "$jesse_check" ]]; then
        JESSE_DIR="$jesse_check"
    fi
fi

if [[ -z "$JESSE_DIR" ]]; then
    error "Could not find jesse package in $VENV_PATH"
    exit 1
fi

info "Found jesse at: $JESSE_DIR"

SITE_PACKAGES=$(dirname "$JESSE_DIR")

# === CHECK MARKER ===

MARKER_PATH="$JESSE_DIR/$MARKER_FILE"

if [[ -f "$MARKER_PATH" ]]; then
    existing_hash=$(cat "$MARKER_PATH")
    if [[ "$existing_hash" == "$SCRIPT_VERSION" ]]; then
        info "Jesse already patched (version $SCRIPT_VERSION). Skipping."
        exit 0
    else
        warn "Jesse patched with different version ($existing_hash). Re-patching."
    fi
fi

# === PATCH 1: jesse/__init__.py ===

info "Patching jesse/__init__.py ..."

cat > "$JESSE_DIR/__init__.py" << 'PYEOF'
import os
import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)

JESSE_DIR = os.path.dirname(os.path.abspath(__file__))
PYEOF

info "  -> Stripped fastapi/controller/router/static/CLI imports"

# === PATCH 2: jesse/research/__init__.py ===

info "Patching jesse/research/__init__.py ..."

RESEARCH_DIR="$JESSE_DIR/research"
if [[ ! -d "$RESEARCH_DIR" ]]; then
    error "jesse/research not found at $RESEARCH_DIR"
    exit 1
fi

cat > "$RESEARCH_DIR/__init__.py" << 'PYEOF'
from .candles import get_candles, store_candles, fake_candle, fake_range_candles, candles_from_close_prices
from .backtest import backtest
from .import_candles import import_candles
from .rule_significance_testing import rule_significance_test, plot_significance_test


def __getattr__(name):
    if name in ("monte_carlo_trades", "monte_carlo_candles"):
        from .monte_carlo import monte_carlo_trades, monte_carlo_candles
        return monte_carlo_trades if name == "monte_carlo_trades" else monte_carlo_candles
    if name in ("gather_ml_data", "train_model", "load_ml_data_csv", "load_ml_model"):
        from .ml import gather_ml_data, train_model, load_ml_data_csv, load_ml_model
        return {"gather_ml_data": gather_ml_data, "train_model": train_model,
                "load_ml_data_csv": load_ml_data_csv, "load_ml_model": load_ml_model}[name]
    if name in ("optimize", "print_optimize_summary"):
        from .optimize import optimize, print_optimize_summary
        return optimize if name == "optimize" else print_optimize_summary
    raise AttributeError(f"module 'jesse.research' has no attribute {name}")
PYEOF

info "  -> Made ray/optuna/scikit-learn lazy-loaded"

# === PATCH 3: aioredis.py stub ===

info "Patching aioredis.py stub ..."

cat > "$SITE_PACKAGES/aioredis.py" << 'PYEOF'
"""Stub aioredis for jesse compatibility (redis>=4 includes asyncio natively)."""
import asyncio
import redis.asyncio as _aioredis


class _RedisPool:
    """Fake redis pool that mimics aioredis v1 create_redis_pool."""

    def __init__(self, *args, **kwargs):
        self._redis = _aioredis.Redis(
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 6379),
            password=kwargs.get("password"),
            db=kwargs.get("db", 0),
            decode_responses=kwargs.get("decode_responses", True),
        )

    async def publish(self, channel, message):
        await self._redis.publish(channel, message)

    def close(self):
        pass

    async def wait_closed(self):
        pass


async def create_redis_pool(address=None, password=None, db=0, **kwargs):
    host, port = address if address else ("localhost", 6379)
    pool = _RedisPool(host=host, port=port, password=password, db=db, **kwargs)
    return pool
PYEOF

info "  -> Created aioredis stub for redis>=4 compatibility"

# === WRITE MARKER ===

echo "$SCRIPT_VERSION" > "$MARKER_PATH"
info "Wrote marker file: $MARKER_PATH"

# === VERIFY ===

info "Verifying patched imports ..."

verify_output=$("$PYTHON" -c "import jesse.helpers as jh; from jesse import research; print('OK')" 2>&1)

if echo "$verify_output" | grep -q "OK"; then
    info "✅ Jesse slim-patched successfully (v$SCRIPT_VERSION)"
else
    error "Verification failed:"
    error "$verify_output"
    exit 1
fi
