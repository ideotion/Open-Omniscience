"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Pillar 4: Real-Time Monitoring & Alerting System - Trend Prediction Models

Machine learning models for trend prediction and analysis.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import logging
from sklearn.linear_model import LinearRegression, BayesianRidge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit
import joblib
import os


class TrendModelType(Enum):
    LINEAR_REGRESSION = "linear_regression"
    POLYNOMIAL_REGRESSION = "polynomial_regression"
    BAYESIAN_RIDGE = "bayesian_ridge"
    RANDOM_FOREST = "random_forest"
    ARIMA = "arima"  # Placeholder for future implementation


class TrendModelStatus(Enum):
    NOT_TRAINED = "not_trained"
    TRAINING = "training"
    TRAINED = "trained"
    ERROR = "error"


@dataclass
class TrendModelConfig:
    """Configuration for a trend prediction model."""
    model_type: TrendModelType
    degree: int = 2  # For polynomial regression
    n_estimators: int = 100  # For Random Forest
    max_depth: Optional[int] = None  # For Random Forest
    lookback_window: int = 10  # Number of previous time steps to use for prediction
    forecast_horizon: int = 5  # Number of time steps to forecast ahead
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrendTrainingResult:
    """Result of trend model training."""
    model_id: str
    status: TrendModelStatus
    training_time: float
    samples_trained: int
    features_used: int
    error: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrendPrediction:
    """Result of a trend prediction."""
    model_id: str
    timestamp: float
    predicted_value: float
    confidence: float
    lower_bound: float
    upper_bound: float
    actual_value: Optional[float] = None
    error: Optional[float] = None


class TrendPredictionModel:
    """
    Trend prediction model with support for:
    - Linear regression
    - Polynomial regression
    - Bayesian ridge regression
    - Random forest regression
    - Time series forecasting
    """

    def __init__(self, config: TrendModelConfig):
        """
        Initialize a trend prediction model.

        Args:
            config: Model configuration.
        """
        self.config = config
        self.model = self._create_model()
        self.poly_features = None
        self.pipeline = None
        self.status = TrendModelStatus.NOT_TRAINED
        self.trained_at: float = 0.0
        self.training_samples: int = 0
        self.logger = logging.getLogger(f"TrendPredictionModel({config.model_type.value})")

    def _create_model(self):
        """Create the appropriate model based on configuration."""
        if self.config.model_type == TrendModelType.LINEAR_REGRESSION:
            return LinearRegression()
        elif self.config.model_type == TrendModelType.POLYNOMIAL_REGRESSION:
            self.poly_features = PolynomialFeatures(degree=self.config.degree)
            self.pipeline = Pipeline([
                ("poly", self.poly_features),
                ("linear", LinearRegression()),
            ])
            return self.pipeline
        elif self.config.model_type == TrendModelType.BAYESIAN_RIDGE:
            return BayesianRidge()
        elif self.config.model_type == TrendModelType.RANDOM_FOREST:
            return RandomForestRegressor(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                random_state=42,
            )
        else:
            raise ValueError(f"Unsupported model type: {self.config.model_type}")

    def prepare_time_series_data(
        self,
        time_series: np.ndarray,
        lookback: Optional[int] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare time series data for supervised learning.

        Args:
            time_series: 1D array of time series values.
            lookback: Number of previous time steps to use (defaults to config).

        Returns:
            Tuple of (X, y) where X is the feature matrix and y is the target vector.
        """
        if lookback is None:
            lookback = self.config.lookback_window

        X, y = [], []
        for i in range(len(time_series) - lookback):
            X.append(time_series[i:i + lookback])
            y.append(time_series[i + lookback])

        return np.array(X), np.array(y)

    def train(self, X: np.ndarray, y: np.ndarray) -> TrendTrainingResult:
        """
        Train the model.

        Args:
            X: Feature matrix (n_samples, n_features).
            y: Target values (n_samples,).

        Returns:
            Training result.
        """
        start_time = time.time()
        self.status = TrendModelStatus.TRAINING

        try:
            if self.pipeline:
                self.pipeline.fit(X, y)
            else:
                self.model.fit(X, y)

            self.status = TrendModelStatus.TRAINED
            self.trained_at = time.time()
            self.training_samples = X.shape[0]

            training_time = time.time() - start_time

            # Calculate training metrics (simplified)
            if X.shape[0] > 1:
                y_pred = self.predict(X)
                mse = np.mean((y_pred - y) ** 2)
                mae = np.mean(np.abs(y_pred - y))

                self.logger.info(
                    f"Trained {self.config.model_type.value} model on {X.shape[0]} samples "
                    f"with {X.shape[1]} features in {training_time:.2f}s (MSE: {mse:.4f}, MAE: {mae:.4f})"
                )

                return TrendTrainingResult(
                    model_id=self.config.model_type.value,
                    status=self.status,
                    training_time=training_time,
                    samples_trained=X.shape[0],
                    features_used=X.shape[1],
                    metrics={"mse": float(mse), "mae": float(mae)},
                )
            else:
                return TrendTrainingResult(
                    model_id=self.config.model_type.value,
                    status=self.status,
                    training_time=training_time,
                    samples_trained=X.shape[0],
                    features_used=X.shape[1],
                )

        except Exception as e:
            self.status = TrendModelStatus.ERROR
            self.logger.error(f"Error training model: {e}")
            return TrendTrainingResult(
                model_id=self.config.model_type.value,
                status=self.status,
                training_time=time.time() - start_time,
                samples_trained=0,
                features_used=0,
                error=str(e),
            )

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make predictions.

        Args:
            X: Feature matrix (n_samples, n_features).

        Returns:
            Predicted values (n_samples,).
        """
        if self.status != TrendModelStatus.TRAINED:
            self.logger.warning(f"Model not trained, cannot predict")
            return np.zeros(X.shape[0])

        try:
            if self.pipeline:
                return self.pipeline.predict(X)
            else:
                return self.model.predict(X)
        except Exception as e:
            self.logger.error(f"Error predicting: {e}")
            return np.zeros(X.shape[0])

    def forecast(self, time_series: np.ndarray, steps: Optional[int] = None) -> List[TrendPrediction]:
        """
        Forecast future values of a time series.

        Args:
            time_series: 1D array of historical time series values.
            steps: Number of steps to forecast (defaults to config).

        Returns:
            List of trend predictions.
        """
        if steps is None:
            steps = self.config.forecast_horizon

        if self.status != TrendModelStatus.TRAINED:
            self.logger.warning(f"Model not trained, cannot forecast")
            return []

        # Prepare data
        X, y = self.prepare_time_series_data(time_series)

        if X.shape[0] == 0:
            return []

        predictions = []
        current_window = time_series[-self.config.lookback_window:]

        for i in range(steps):
            # Predict next value
            next_pred = self.predict(current_window.reshape(1, -1))[0]

            # Calculate confidence (simplified)
            if hasattr(self.model, "predict"):
                if self.config.model_type == TrendModelType.BAYESIAN_RIDGE:
                    # Bayesian Ridge provides uncertainty estimates
                    std = np.sqrt(self.model.alpha_)
                    confidence = 1.0 / (1.0 + std)
                    lower = next_pred - 1.96 * std
                    upper = next_pred + 1.96 * std
                else:
                    # For other models, use a fixed confidence
                    confidence = 0.8
                    lower = next_pred * 0.95
                    upper = next_pred * 1.05
            else:
                confidence = 0.8
                lower = next_pred * 0.95
                upper = next_pred * 1.05

            predictions.append(TrendPrediction(
                model_id=self.config.model_type.value,
                timestamp=time.time() + (i + 1) * (time_series[-1] - time_series[-2]) if len(time_series) > 1 else time.time(),
                predicted_value=float(next_pred),
                confidence=float(confidence),
                lower_bound=float(lower),
                upper_bound=float(upper),
            ))

            # Update window for next prediction
            current_window = np.append(current_window[1:], next_pred)

        return predictions

    def save(self, path: str) -> bool:
        """
        Save the model to disk.

        Args:
            path: Path to save the model.

        Returns:
            True if successful, False otherwise.
        """
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            joblib.dump({
                "config": self.config,
                "model": self.model,
                "pipeline": self.pipeline,
                "poly_features": self.poly_features,
                "status": self.status,
                "trained_at": self.trained_at,
                "training_samples": self.training_samples,
            }, path)
            self.logger.info(f"Model saved to {path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving model: {e}")
            return False

    @classmethod
    def load(cls, path: str) -> "TrendPredictionModel":
        """
        Load a model from disk.

        Args:
            path: Path to the saved model.

        Returns:
            Loaded TrendPredictionModel instance.
        """
        try:
            data = joblib.load(path)
            config = data["config"]
            model = cls(config)
            model.model = data["model"]
            model.pipeline = data.get("pipeline")
            model.poly_features = data.get("poly_features")
            model.status = data["status"]
            model.trained_at = data["trained_at"]
            model.training_samples = data["training_samples"]
            model.logger.info(f"Model loaded from {path}")
            return model
        except Exception as e:
            raise ValueError(f"Error loading model: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get model statistics."""
        return {
            "model_type": self.config.model_type.value,
            "status": self.status.value,
            "trained_at": self.trained_at,
            "training_samples": self.training_samples,
            "lookback_window": self.config.lookback_window,
            "forecast_horizon": self.config.forecast_horizon,
        }


class TrendModelRegistry:
    """
    Registry for managing multiple trend prediction models.
    """

    def __init__(self):
        """Initialize the model registry."""
        self.models: Dict[str, TrendPredictionModel] = {}
        self.logger = logging.getLogger("TrendModelRegistry")

    def register_model(self, model_id: str, model: TrendPredictionModel) -> None:
        """Register a model."""
        self.models[model_id] = model
        self.logger.info(f"Registered trend model: {model_id}")

    def unregister_model(self, model_id: str) -> bool:
        """Unregister a model."""
        if model_id in self.models:
            del self.models[model_id]
            self.logger.info(f"Unregistered trend model: {model_id}")
            return True
        return False

    def get_model(self, model_id: str) -> Optional[TrendPredictionModel]:
        """Get a model by ID."""
        return self.models.get(model_id)

    def list_models(self) -> List[str]:
        """List all registered model IDs."""
        return list(self.models.keys())

    def train_model(
        self,
        model_id: str,
        X: np.ndarray,
        y: np.ndarray,
    ) -> TrendTrainingResult:
        """Train a model."""
        model = self.models.get(model_id)
        if not model:
            return TrendTrainingResult(
                model_id=model_id,
                status=TrendModelStatus.ERROR,
                error=f"Model {model_id} not found",
            )
        return model.train(X, y)

    def forecast(self, model_id: str, time_series: np.ndarray, steps: Optional[int] = None) -> List[TrendPrediction]:
        """Make forecasts with a model."""
        model = self.models.get(model_id)
        if not model:
            return []
        return model.forecast(time_series, steps)

    def save_all(self, directory: str) -> Dict[str, bool]:
        """Save all models to a directory."""
        results = {}
        for model_id, model in self.models.items():
            path = os.path.join(directory, f"{model_id}.pkl")
            results[model_id] = model.save(path)
        return results

    def load_all(self, directory: str) -> Dict[str, bool]:
        """Load all models from a directory."""
        results = {}
        if not os.path.exists(directory):
            return results

        for filename in os.listdir(directory):
            if filename.endswith(".pkl"):
                model_id = filename[:-4]
                try:
                    path = os.path.join(directory, filename)
                    model = TrendPredictionModel.load(path)
                    self.register_model(model_id, model)
                    results[model_id] = True
                except Exception as e:
                    results[model_id] = False
                    self.logger.error(f"Error loading trend model {model_id}: {e}")

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        trained = sum(1 for m in self.models.values() if m.status == TrendModelStatus.TRAINED)
        return {
            "total_models": len(self.models),
            "trained_models": trained,
            "not_trained": len(self.models) - trained,
        }
