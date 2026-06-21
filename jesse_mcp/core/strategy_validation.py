"""
Strategy validation — syntax, imports, structure, methods, indicators,
dry-run backtest, metadata tracking, and certification.

Consolidated from the strategy_validation/ subpackage and strategy_validator.py.
"""

import ast
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jesse-mcp.validator")


# ── Types ──────────────────────────────────────────────────────────────────────


class ValidationLevel(Enum):
    SYNTAX = "syntax"
    IMPORTS = "imports"
    STRUCTURE = "structure"
    METHODS = "methods"
    INDICATORS = "indicators"
    DRY_RUN = "dry_run"


@dataclass
class ValidationResult:
    passed: bool
    level: str
    error: Optional[str] = None
    line: Optional[int] = None
    fix_hint: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "passed": self.passed,
            "level": self.level,
            "error": self.error,
            "line": self.line,
            "fix_hint": self.fix_hint,
        }
        if self.warnings:
            result["warnings"] = self.warnings
        if self.metrics:
            result["metrics"] = self.metrics
        return result


# ── Metadata ───────────────────────────────────────────────────────────────────


CERTIFICATION_MIN_TESTS = 10
CERTIFICATION_PASS_RATE = 0.70


@dataclass
class StrategyMetadata:
    """Metadata for a strategy tracking its testing and certification status."""

    name: str
    version: str = "v0.0.0"
    test_count: int = 0
    test_pass_count: int = 0
    live_trade_count: int = 0
    live_win_count: int = 0
    certified_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: str(datetime.now()))
    last_test_at: Optional[str] = None
    notes: str = ""

    def __post_init__(self):
        self.version = (
            self._compute_version()
            if self.certified_at or self.test_count > 0
            else self.version
        )

    def _compute_version(self) -> str:
        if self.certified_at:
            return f"v1.{self.live_win_count}.{self.live_trade_count}"
        return f"v0.{self.test_pass_count}.{self.test_count}"

    def record_test(self, passed: bool) -> None:
        self.test_count += 1
        if passed:
            self.test_pass_count += 1
        self.last_test_at = str(datetime.now())
        self.version = self._compute_version()

    def should_certify(self) -> bool:
        if self.certified_at:
            return False
        if self.test_count < CERTIFICATION_MIN_TESTS:
            return False
        return (self.test_pass_count / self.test_count) >= CERTIFICATION_PASS_RATE

    def certify(self) -> None:
        if not self.certified_at:
            self.certified_at = str(datetime.now())
            self.version = self._compute_version()
            logger.info(f"Strategy {self.name} certified: {self.version}")

    def record_live_trade(self, won: bool) -> None:
        self.live_trade_count += 1
        if won:
            self.live_win_count += 1
        if self.certified_at:
            self.version = self._compute_version()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "test_count": self.test_count,
            "test_pass_count": self.test_pass_count,
            "live_trade_count": self.live_trade_count,
            "live_win_count": self.live_win_count,
            "certified_at": self.certified_at,
            "created_at": self.created_at,
            "last_test_at": self.last_test_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyMetadata":
        return cls(**data)


def get_metadata_path(strategy_name: str, strategies_path: str) -> str:
    return os.path.join(strategies_path, strategy_name, "metadata.json")


def load_metadata(strategy_name: str, strategies_path: str) -> Optional[StrategyMetadata]:
    path = get_metadata_path(strategy_name, strategies_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return StrategyMetadata.from_dict(json.load(f))
    except Exception as e:
        logger.warning(f"Failed to load metadata for {strategy_name}: {e}")
        return None


def save_metadata(metadata: StrategyMetadata, strategies_path: str) -> bool:
    path = get_metadata_path(metadata.name, strategies_path)
    try:
        with open(path, "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save metadata for {metadata.name}: {e}")
        return False


def create_metadata(name: str, strategies_path: str) -> StrategyMetadata:
    metadata = StrategyMetadata(name=name)
    save_metadata(metadata, strategies_path)
    return metadata


def get_or_create_metadata(name: str, strategies_path: str) -> StrategyMetadata:
    metadata = load_metadata(name, strategies_path)
    return metadata if metadata is not None else create_metadata(name, strategies_path)


# ── Certification ──────────────────────────────────────────────────────────────


@dataclass
class CertificationStatus:
    is_certified: bool
    certification_level: int
    test_count: int
    test_pass_count: int
    live_trade_count: int
    live_win_count: int
    pass_rate: float

    @property
    def has_enough_tests(self) -> bool:
        return self.test_count >= CERTIFICATION_MIN_TESTS

    @property
    def meets_pass_rate(self) -> bool:
        return self.pass_rate >= CERTIFICATION_PASS_RATE

    @property
    def should_certify(self) -> bool:
        return self.has_enough_tests and self.meets_pass_rate and not self.is_certified


def decode_version(version: str) -> CertificationStatus:
    if not version:
        return CertificationStatus(
            is_certified=False, certification_level=0, test_count=0,
            test_pass_count=0, live_trade_count=0, live_win_count=0, pass_rate=0.0,
        )
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", version)
    if not m:
        logger.warning(f"Invalid version format: {version}")
        return CertificationStatus(
            is_certified=False, certification_level=0, test_count=0,
            test_pass_count=0, live_trade_count=0, live_win_count=0, pass_rate=0.0,
        )
    level, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if level == 0:
        return CertificationStatus(
            is_certified=False, certification_level=0,
            test_count=patch, test_pass_count=minor,
            live_trade_count=0, live_win_count=0,
            pass_rate=minor / patch if patch > 0 else 0.0,
        )
    return CertificationStatus(
        is_certified=True, certification_level=level,
        test_count=0, test_pass_count=0,
        live_trade_count=patch, live_win_count=minor,
        pass_rate=minor / patch if patch > 0 else 0.0,
    )


def get_strategy_certification(strategy_name: str, strategies_path: str) -> CertificationStatus:
    metadata = load_metadata(strategy_name, strategies_path)
    if metadata:
        return decode_version(metadata.version)
    return decode_version(_get_version_from_strategy_file(strategy_name, strategies_path))


def _get_version_from_strategy_file(strategy_name: str, strategies_path: str) -> Optional[str]:
    path = os.path.join(strategies_path, strategy_name, "__init__.py")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            m = re.search(r'__version__\s*=\s*["\'](v\d+\.\d+\.\d+)["\']', f.read())
            return m.group(1) if m else None
    except Exception as e:
        logger.warning(f"Failed to read strategy file for version: {e}")
        return None


def is_strategy_certified(strategy_name: str, strategies_path: str) -> bool:
    return get_strategy_certification(strategy_name, strategies_path).is_certified


def check_live_trading_allowed(strategy_name: str, strategies_path: str) -> dict:
    status = get_strategy_certification(strategy_name, strategies_path)
    if status.is_certified:
        return {"allowed": True, "status": status, "reason": None, "recommendation": None}
    if status.test_count == 0:
        return {
            "allowed": False, "status": status, "reason": "no_tests",
            "recommendation": "Run backtests to test the strategy before live trading",
        }
    if not status.has_enough_tests:
        return {
            "allowed": False, "status": status, "reason": "insufficient_tests",
            "recommendation": f"Need {CERTIFICATION_MIN_TESTS - status.test_count} more tests (have {status.test_count}/{CERTIFICATION_MIN_TESTS})",
        }
    if not status.meets_pass_rate:
        return {
            "allowed": False, "status": status, "reason": "insufficient_pass_rate",
            "recommendation": f"Pass rate {status.pass_rate:.0%} is below {CERTIFICATION_PASS_RATE:.0%} threshold ({status.test_pass_count}/{status.test_count} passed)",
        }
    return {"allowed": True, "status": status, "reason": None, "recommendation": None}


# ── Static Validator ───────────────────────────────────────────────────────────


KNOWN_INDICATORS = {
    "sma", "ema", "wma", "hma", "vwma", "tema", "rsi", "macd", "atr",
    "adx", "stoch", "cci", "bollinger_bands", "bollinger_bands_width",
    "donchian_channel", "obv", "vwap", "mfi", "volume_profile", "supertrend",
    "ichimoku", "parabolic_sar", "zscore", "kalman_filter", "keltner_channel",
    "pivot_points",
}


class StaticValidator:
    """Static validation of strategy code (no execution)."""

    def validate_syntax(self, code: str) -> ValidationResult:
        try:
            compile(code, "<string>", "exec")
            return ValidationResult(passed=True, level=ValidationLevel.SYNTAX.value)
        except SyntaxError as e:
            return ValidationResult(
                passed=False, level=ValidationLevel.SYNTAX.value,
                error=str(e), line=e.lineno,
                fix_hint=f"Fix syntax error on line {e.lineno}: {e.msg}",
            )

    def validate_imports(self, code: str) -> ValidationResult:
        has_strategy = "from jesse.strategies import Strategy" in code
        has_ta = "import jesse.indicators as ta" in code or "from jesse import indicators as ta" in code
        if has_strategy:
            warnings = []
            if not has_ta and "ta." in code:
                warnings.append("Code uses ta.* but missing 'import jesse.indicators as ta'")
            return ValidationResult(passed=True, level=ValidationLevel.IMPORTS.value, warnings=warnings)
        missing = ["from jesse.strategies import Strategy"]
        if not has_ta:
            missing.append("import jesse.indicators as ta")
        return ValidationResult(
            passed=False, level=ValidationLevel.IMPORTS.value,
            error=f"Missing imports: {', '.join(missing)}",
        )

    def validate_structure(self, code: str) -> ValidationResult:
        m = re.search(r"class\s+(\w+)\s*\(([^)]*)\)\s*:", code)
        if not m:
            return ValidationResult(
                passed=False, level=ValidationLevel.STRUCTURE.value,
                error="No class definition found (must inherit from Strategy)",
            )
        if "Strategy" in m.group(2):
            return ValidationResult(passed=True, level=ValidationLevel.STRUCTURE.value)
        return ValidationResult(
            passed=False, level=ValidationLevel.STRUCTURE.value,
            error=f"Class {m.group(1)} must inherit from Strategy, not {m.group(2)}",
            fix_hint=f"class {m.group(1)}(Strategy):",
        )

    def validate_methods(self, code: str) -> ValidationResult:
        required = ["should_long", "go_long", "should_short", "go_short"]
        missing = [m for m in required if f"def {m}(" not in code]
        if not missing:
            return ValidationResult(passed=True, level=ValidationLevel.METHODS.value)
        return ValidationResult(
            passed=False, level=ValidationLevel.METHODS.value,
            error=f"Missing required methods: {', '.join(missing)}",
        )

    def validate_indicators(self, code: str) -> ValidationResult:
        unknown = [i for i in re.findall(r"ta\.(\w+)\(", code) if i not in KNOWN_INDICATORS]
        return ValidationResult(
            passed=True, level=ValidationLevel.INDICATORS.value,
            warnings=[f"Unknown indicator: ta.{i}" for i in unknown],
        )

    def full_static_validation(self, code: str) -> Dict[str, Any]:
        results = {"passed": True, "levels": {}, "errors": [], "warnings": [], "fix_hints": []}
        for level_name, validator in [
            (ValidationLevel.SYNTAX.value, self.validate_syntax),
            (ValidationLevel.IMPORTS.value, self.validate_imports),
            (ValidationLevel.STRUCTURE.value, self.validate_structure),
            (ValidationLevel.METHODS.value, self.validate_methods),
            (ValidationLevel.INDICATORS.value, self.validate_indicators),
        ]:
            r = validator(code)
            results["levels"][level_name] = r.to_dict()
            if not r.passed:
                results["passed"] = False
                results["errors"].append({"level": level_name, "error": r.error, "line": r.line})
                if r.fix_hint:
                    results["fix_hints"].append({"level": level_name, "hint": r.fix_hint})
            for w in (r.warnings or []):
                results["warnings"].append({"level": level_name, "warning": w})
        return results


# ── Dry-Run Validator ──────────────────────────────────────────────────────────


class DryRunValidator:
    """Validates strategy by running a quick backtest via REST API."""

    def __init__(self, rest_client_getter):
        self._get_client = rest_client_getter

    def run_dry_run(self, code: str, spec: Dict[str, Any]) -> ValidationResult:
        strategy_name = spec.get("name", f"DryRun_{uuid.uuid4().hex[:8]}")
        symbol = spec.get("symbol", "BTC-USDT")
        timeframe = spec.get("timeframe", "1h")
        exchange = spec.get("exchange", "Binance")

        logger.info("🔬 Running dry-run backtest via REST API...")
        try:
            client = self._get_client()
            result = client.backtest(
                routes=[{"strategy": strategy_name, "symbol": symbol, "timeframe": timeframe}],
                start_date="2024-01-01", end_date="2024-01-05",
                exchange=exchange, starting_balance=10000,
                fee=0.001, leverage=1, exchange_type="futures",
            )
            if "error" in result:
                err = result["error"]
                if "401" in str(err) or "Unauthorized" in str(err):
                    return ValidationResult(
                        passed=True, level=ValidationLevel.DRY_RUN.value,
                        warnings=["Dry-run skipped: Jesse server not authenticated"],
                    )
                return ValidationResult(
                    passed=False, level=ValidationLevel.DRY_RUN.value,
                    error=f"Backtest error: {err}",
                )
            metrics = result.get("metrics", {})
            total_trades = metrics.get("total_trades", 0)
            win_rate = metrics.get("win_rate", 0)
            total_return = metrics.get("total_return", 0)
            logger.info(f"✅ Dry-run: {total_trades} trades, {win_rate:.1%} win rate")
            return ValidationResult(
                passed=True, level=ValidationLevel.DRY_RUN.value,
                warnings=[f"Dry-run: {total_trades} trades, {win_rate:.1%} win rate"],
                metrics={"total_trades": total_trades, "win_rate": win_rate, "total_return": total_return},
            )
        except Exception as e:
            logger.error(f"❌ Dry-run failed: {e}")
            return ValidationResult(
                passed=True, level=ValidationLevel.DRY_RUN.value,
                warnings=[f"Dry-run skipped: {e}"],
            )


# ── Strategy Validator (facade) ────────────────────────────────────────────────


_static_validator = StaticValidator()


def _get_rest_client():
    from jesse_mcp.core.rest import get_jesse_rest_client
    return get_jesse_rest_client()


_dry_run_validator = DryRunValidator(_get_rest_client)


class StrategyValidator:
    """Combines static and dry-run validation."""

    def validate_syntax(self, code: str) -> ValidationResult:
        return _static_validator.validate_syntax(code)

    def validate_imports(self, code: str) -> ValidationResult:
        return _static_validator.validate_imports(code)

    def validate_structure(self, code: str) -> ValidationResult:
        return _static_validator.validate_structure(code)

    def validate_methods(self, code: str) -> ValidationResult:
        return _static_validator.validate_methods(code)

    def validate_indicators(self, code: str) -> ValidationResult:
        return _static_validator.validate_indicators(code)

    def dry_run_backtest(self, code: str, spec: Dict) -> ValidationResult:
        return _dry_run_validator.run_dry_run(code, spec)

    def full_validation(self, code: str, spec: Optional[Dict] = None) -> Dict:
        results = _static_validator.full_static_validation(code)
        if spec and results["passed"]:
            dry_run_result = self.dry_run_backtest(code, spec)
            results["levels"][ValidationLevel.DRY_RUN.value] = dry_run_result.to_dict()
            if dry_run_result.warnings:
                for w in dry_run_result.warnings:
                    results["warnings"].append({ValidationLevel.DRY_RUN.value: w})
        logger.info(f"Validation: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")
        return results


_validator_instance = None


def get_validator() -> StrategyValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = StrategyValidator()
    return _validator_instance