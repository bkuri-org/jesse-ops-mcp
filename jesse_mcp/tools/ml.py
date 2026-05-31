"""
Phase ML: Machine Learning Tools

Exposes Jesse's built-in ML pipeline functions as MCP tools:
- gather_ml_data: Run gather-mode backtest to collect ML training data
- train_model: Train sklearn estimator on gathered data
- load_ml_data_csv: Load previously saved CSV data
- load_ml_model: Load a previously trained model for inspection
- ml_predict: Run inference with a trained model on feature values
"""

import logging
from typing import Any, Dict, List, Optional

from jesse_mcp.tools._utils import async_call, require_jesse, tool_error_handler

logger = logging.getLogger("jesse-mcp.ml")

# Whitelisted sklearn estimators for safety
SUPPORTED_CLASSIFIERS = {
    "RandomForestClassifier",
    "GradientBoostingClassifier",
    "LogisticRegression",
    "CalibratedClassifierCV",
}
SUPPORTED_REGRESSORS = {
    "RandomForestRegressor",
    "GradientBoostingRegressor",
    "Ridge",
}
SUPPORTED_ESTIMATORS = SUPPORTED_CLASSIFIERS | SUPPORTED_REGRESSORS


def _construct_estimator(estimator_type: str, params: Optional[Dict[str, Any]] = None):
    """Construct a whitelisted sklearn estimator from type name and params."""
    if estimator_type not in SUPPORTED_ESTIMATORS:
        raise ValueError(
            f"Unsupported estimator '{estimator_type}'. "
            f"Supported: {sorted(SUPPORTED_ESTIMATORS)}"
        )

    from sklearn.ensemble import (
        GradientBoostingClassifier,
        GradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.linear_model import LogisticRegression, Ridge

    registry = {
        "RandomForestClassifier": RandomForestClassifier,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "LogisticRegression": LogisticRegression,
        "RandomForestRegressor": RandomForestRegressor,
        "GradientBoostingRegressor": GradientBoostingRegressor,
        "Ridge": Ridge,
    }

    cls = registry[estimator_type]
    kwargs = params or {}

    # Add sensible defaults
    if "random_state" not in kwargs:
        kwargs["random_state"] = 42

    return cls(**kwargs)


def register_ml_tools(mcp):
    """Register ML tools with the MCP server."""

    @mcp.tool
    @tool_error_handler
    async def gather_ml_data(
        strategy: str,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        exchange: str = "Binance",
        starting_balance: float = 10000,
        fee: float = 0.0007,
        exchange_type: str = "futures",
        leverage: int = 10,
        warm_up_candles: int = 210,
        data_routes: Optional[List[Dict[str, str]]] = None,
        csv_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a gather-mode backtest to collect ML training data from a Jesse strategy.

        The strategy's record_features() and record_label() calls collect labelled
        feature samples. Data is saved to strategies/<Name>/ml_data/<Name>_data.csv.

        Use this before train_model to prepare training data.

        Args:
            strategy: Jesse strategy class name (e.g. 'SMACrossover')
            symbol: Trading pair (e.g. 'BTC-USDT')
            timeframe: Candle timeframe (e.g. '1h', '4h')
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            exchange: Exchange name (default: 'Binance')
            starting_balance: Starting balance (default: 10000)
            fee: Trading fee (default: 0.0007)
            exchange_type: 'spot' or 'futures' (default: 'futures')
            leverage: Futures leverage (default: 10)
            warm_up_candles: Warm-up candle count (default: 210)
            data_routes: Extra data routes for multi-timeframe features
            csv_path: Custom CSV save path, 'auto' for default (default: None)
        """
        jesse = require_jesse()
        if jesse is None:
            return {
                "error": "Jesse research module not available",
                "error_type": "ModuleUnavailable",
                "hint": "Install jesse with research support",
            }

        from jesse import research
        from jesse.enums import FuturesExchangeType, ExchangeType
        from jesse.routes import Route

        # Build routes
        routes = [
            Route(exchange, symbol, timeframe, strategy)
        ]

        extra_routes = []
        if data_routes:
            for dr in data_routes:
                extra_routes.append(
                    Route(dr["exchange"], dr["symbol"], dr["timeframe"])
                )

        # Build config dict
        ex_type = (
            FuturesExchangeType(exchange_type)
            if exchange_type == "futures"
            else ExchangeType(exchange_type)
        )

        config = {
            "starting_balance": starting_balance,
            "fee": fee,
            "type": ex_type,
            "futures_leverage": leverage,
            "futures_leverage_mode": 1,
            "exchange": exchange,
            "warm_up_candles": warm_up_candles,
        }

        # Fetch candles
        start_ts = research.string_to_timestamp(start_date)
        end_ts = research.string_to_timestamp(end_date)
        candles, warmup_candles = research.get_candles(
            exchange, symbol, timeframe, start_ts, end_ts,
            warm_up_candles, caching=True, is_for_jesse=True
        )

        # Build candle dicts
        candles_dict = {
            f"{exchange}-{symbol}-{timeframe}": {
                "exchange": exchange,
                "symbol": symbol,
                "candles": candles,
            }
        }
        warmup_dict = {
            f"{exchange}-{symbol}-{timeframe}": {
                "exchange": exchange,
                "symbol": symbol,
                "candles": warmup_candles,
            }
        }

        # Extra candle data for data_routes
        for dr in (data_routes or []):
            dr_candles, dr_warmup = research.get_candles(
                dr["exchange"], dr["symbol"], dr["timeframe"],
                start_ts, end_ts, warm_up_candles,
                caching=True, is_for_jesse=True,
            )
            key = f"{dr['exchange']}-{dr['symbol']}-{dr['timeframe']}"
            candles_dict[key] = {
                "exchange": dr["exchange"],
                "symbol": dr["symbol"],
                "candles": dr_candles,
            }
            warmup_dict[key] = {
                "exchange": dr["exchange"],
                "symbol": dr["symbol"],
                "candles": dr_warmup,
            }

        # Run gather
        result = await async_call(
            research.ml.gather_ml_data,
            config, routes, extra_routes,
            candles_dict, warmup_dict,
            csv_path=csv_path or "auto",
        )

        return {
            "success": True,
            "data_points": result.get("data_points", len(result.get("data", []))),
            "csv_path": result.get("csv_path", result.get("path")),
            "features": result.get("features"),
            "label": result.get("label"),
        }

    @mcp.tool
    @tool_error_handler
    async def train_model(
        data_path: str,
        estimator_type: str = "RandomForestClassifier",
        estimator_params: Optional[Dict[str, Any]] = None,
        task: str = "binary",
        test_ratio: float = 0.2,
        save_to: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Train an ML model on gathered feature data using a whitelisted sklearn estimator.

        Supported estimators:
        - Classifiers: RandomForestClassifier, GradientBoostingClassifier, LogisticRegression
        - Regressors: RandomForestRegressor, GradientBoostingRegressor, Ridge

        Task types: 'binary', 'multiclass', 'regression'

        Use this after gather_ml_data to train a predictive model.

        Args:
            data_path: Path to CSV data or strategy name (auto-resolves)
            estimator_type: sklearn estimator class name
            estimator_params: Parameters for the estimator
            task: 'binary', 'multiclass', or 'regression'
            test_ratio: Train/test split ratio (default: 0.2)
            save_to: Directory to save model artifacts (default: auto)
            model_name: Model name prefix (default: auto)
        """
        jesse = require_jesse()
        if jesse is None:
            return {
                "error": "Jesse research module not available",
                "error_type": "ModuleUnavailable",
            }

        # Load data
        data = await async_call(
            jesse.research.ml.load_ml_data_csv, data_path
        )

        # Construct estimator
        estimator = _construct_estimator(estimator_type, estimator_params)

        # Determine save path
        if save_to is None and model_name is None:
            save_to = None  # Let Jesse auto-determine
            model_name = estimator_type.lower()

        # Train
        result = await async_call(
            jesse.research.ml.train_model,
            data, estimator, task, test_ratio, save_to, model_name,
        )

        # Clean up non-serializable fields
        clean_result = {
            "success": True,
            "task": task,
            "estimator": estimator_type,
            "data_points": len(data),
            "train_size": result.get("train_test_info", {}).get("train_size", 0),
            "test_size": result.get("train_test_info", {}).get("test_size", 0),
            "feature_names": result.get("feature_names", []),
            "metrics": _serialize_metrics(result.get("metrics", {})),
            "feature_importance": result.get("feature_importance"),
            "feature_impact": result.get("feature_impact"),
            "save_path": result.get("save_path"),
            "model_name": model_name,
        }

        return clean_result

    @mcp.tool
    @tool_error_handler
    async def load_ml_data_csv(
        path_or_name: str,
        max_rows: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Load previously gathered ML data from a CSV file.

        Pass a strategy name (auto-resolves to strategies/<name>/ml_data/) or
        an explicit file path.

        Args:
            path_or_name: Strategy name or CSV file path
            max_rows: Limit loaded rows (default: None for all)
        """
        jesse = require_jesse()
        if jesse is None:
            return {
                "error": "Jesse research module not available",
                "error_type": "ModuleUnavailable",
            }

        data = await async_call(
            jesse.research.ml.load_ml_data_csv, path_or_name
        )

        if max_rows and len(data) > max_rows:
            data = data[:max_rows]

        if not data:
            return {"success": False, "data_points": 0, "error": "No data found"}

        # Extract feature/label names from first sample
        first = data[0]
        feature_names = list(first.get("features", {}).keys()) if isinstance(first.get("features"), dict) else []
        label_info = first.get("label", {})
        label_name = label_info.get("name", "unknown") if isinstance(label_info, dict) else "unknown"

        return {
            "success": True,
            "data_points": len(data),
            "feature_names": feature_names,
            "label_name": label_name,
            "sample_features": first.get("features"),
            "sample_label": label_info,
        }

    @mcp.tool
    @tool_error_handler
    async def load_ml_model(
        path_or_name: str,
    ) -> Dict[str, Any]:
        """
        Load a previously trained ML model for inspection.

        Returns model metadata, feature names, and feature importance
        without loading the full model into memory for inference.

        Args:
            path_or_name: Strategy name or directory path containing model artifacts
        """
        jesse = require_jesse()
        if jesse is None:
            return {
                "error": "Jesse research module not available",
                "error_type": "ModuleUnavailable",
            }

        result = await async_call(
            jesse.research.ml.load_ml_model, path_or_name
        )

        return {
            "success": True,
            "feature_names": result.get("feature_names", []),
            "feature_importance": result.get("feature_importance", {}),
            "model_type": str(type(result.get("model")).__name__) if result.get("model") else None,
            "has_scaler": result.get("scaler") is not None,
        }

    @mcp.tool
    @tool_error_handler
    async def ml_predict(
        model_path_or_name: str,
        features: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Run inference with a trained ML model on feature values.

        Provide feature values as a dict mapping feature names to float values.
        The model must have been previously trained with train_model.

        Returns prediction, probability (for classifiers), and feature values used.

        Args:
            model_path_or_name: Strategy name or directory containing model artifacts
            features: Dict of feature_name -> float value for prediction
        """
        jesse = require_jesse()
        if jesse is None:
            return {
                "error": "Jesse research module not available",
                "error_type": "ModuleUnavailable",
            }

        # Load model
        model_data = await async_call(
            jesse.research.ml.load_ml_model, model_path_or_name
        )

        model = model_data.get("model")
        scaler = model_data.get("scaler")
        feature_names = model_data.get("feature_names", [])

        if model is None:
            return {"error": "Model not found", "success": False}

        # Build feature vector in correct order
        try:
            import numpy as np

            feature_vector = np.array(
                [features.get(name, 0.0) for name in feature_names]
            ).reshape(1, -1)

            if scaler is not None:
                feature_vector = scaler.transform(feature_vector)

            prediction = model.predict(feature_vector)
            result: Dict[str, Any] = {
                "success": True,
                "prediction": prediction.tolist(),
                "features_used": feature_names,
                "feature_values": features,
            }

            # Add probabilities for classifiers
            if hasattr(model, "predict_proba"):
                try:
                    proba = model.predict_proba(feature_vector)
                    result["probabilities"] = proba.tolist()
                except Exception:
                    pass  # Some models don't support predict_proba

            return result

        except Exception as e:
            return {
                "error": f"Prediction failed: {e}",
                "success": False,
                "error_type": type(e).__name__,
            }


def _serialize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Convert ML metrics dict to JSON-serializable form."""
    clean: Dict[str, Any] = {}
    for key, value in metrics.items():
        if hasattr(value, "item"):
            # numpy scalar
            clean[key] = float(value.item())
        elif hasattr(value, "tolist"):
            # numpy array
            clean[key] = value.tolist()
        else:
            clean[key] = value
    return clean
