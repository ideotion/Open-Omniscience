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
Pillar 4: Real-Time Monitoring & Alerting System - Anomaly Detection Models

Machine learning models for anomaly detection.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union
from enum import Enum
import logging
import os
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

# Optional import for model serialization
try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False
    logger = logging.getLogger(__name__)
    logger.warning("joblib not available. Model serialization/deserialization will be limited.")


class ModelType(Enum):
    ISOLATION_FOREST = "isolation_forest"
    ONE_CLASS_SVM = "one_class_svm"
    AUTOENCODER = "autoencoder"  # Placeholder for future implementation


class ModelStatus(Enum):
    NOT_TRAINED = "not_trained"
    TRAINING = "training"
    TRAINED = "trained"
    ERROR = "error"


@dataclass
class ModelConfig:
    """Configuration for an anomaly detection model."""
    model_type: ModelType
    contamination: float = 0.01  # Expected proportion of outliers
    random_state: int = 42
    n_estimators: int = 100  # For Isolation Forest
    kernel: str = "rbf"  # For One-Class SVM
    nu: float = 0.01  # For One-Class SVM
    features: List[str] = field(default_factory=list)  # Feature names
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelTrainingResult:
    """Result of model training."""
    model_id: str
    status: ModelStatus
    training_time: float
    samples_trained: int
    features_used: int
    error: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class AnomalyPrediction:
    """Result of an anomaly prediction."""
    model_id: str
    is_anomaly: bool
    anomaly_score: float  # -1 to 1 (higher = more anomalous)
    threshold: float
    features: Dict[str, float]
    timestamp: float


class AnomalyDetectionModel:
    """
    Anomaly detection model with support for:
    - Isolation Forest
    - One-Class SVM
    - Online learning (incremental updates)
    - Model persistence
    """

    def __init__(self, config: ModelConfig):
        """
        Initialize an anomaly detection model.

        Args:
            config: Model configuration.
        """
        self.config = config
        self.model = self._create_model()
        self.scaler = StandardScaler()
        self.pipeline = Pipeline([
            ("scaler", self.scaler),
            ("model", self.model),
        ])
        self.status = ModelStatus.NOT_TRAINED
        self.trained_at: float = 0.0
        self.training_samples: int = 0
        self.logger = logging.getLogger(f"AnomalyDetectionModel({config.model_type.value})")

    def _create_model(self):
        """Create the appropriate model based on configuration."""
        if self.config.model_type == ModelType.ISOLATION_FOREST:
            return IsolationForest(
                n_estimators=self.config.n_estimators,
                contamination=self.config.contamination,
                random_state=self.config.random_state,
            )
        elif self.config.model_type == ModelType.ONE_CLASS_SVM:
            return OneClassSVM(
                kernel=self.config.kernel,
                nu=self.config.nu,
                random_state=self.config.random_state,
            )
        else:
            raise ValueError(f"Unsupported model type: {self.config.model_type}")

    def train(self, X: np.ndarray, y: Optional[np.ndarray] = None) -> ModelTrainingResult:
        """
        Train the model on normal data.

        Args:
            X: Training data (n_samples, n_features).
            y: Target values (ignored for unsupervised models).

        Returns:
            Training result.
        """
        start_time = time.time()
        self.status = ModelStatus.TRAINING

        try:
            # Fit the pipeline (scaler + model)
            self.pipeline.fit(X)

            # For Isolation Forest, we can set the threshold based on contamination
            if hasattr(self.model, "offset_"):
                # Isolation Forest specific
                self.model.offset_ = np.percentile(
                    -self.model.score_samples(X),
                    100 * self.config.contamination,
                )

            self.status = ModelStatus.TRAINED
            self.trained_at = time.time()
            self.training_samples = X.shape[0]

            training_time = time.time() - start_time

            self.logger.info(
                f"Trained {self.config.model_type.value} model on {X.shape[0]} samples "
                f"with {X.shape[1]} features in {training_time:.2f}s"
            )

            return ModelTrainingResult(
                model_id=self.config.model_type.value,
                status=self.status,
                training_time=training_time,
                samples_trained=X.shape[0],
                features_used=X.shape[1],
            )

        except Exception as e:
            self.status = ModelStatus.ERROR
            self.logger.error(f"Error training model: {e}")
            return ModelTrainingResult(
                model_id=self.config.model_type.value,
                status=self.status,
                training_time=time.time() - start_time,
                samples_trained=0,
                features_used=0,
                error=str(e),
            )

    def predict(self, X: np.ndarray) -> List[AnomalyPrediction]:
        """
        Predict anomalies in new data.

        Args:
            X: Data to predict on (n_samples, n_features).

        Returns:
            List of anomaly predictions.
        """
        if self.status != ModelStatus.TRAINED:
            self.logger.warning(f"Model not trained, cannot predict")
            return []

        try:
            # Get anomaly scores (for Isolation Forest, negative scores are anomalies)
            if self.config.model_type == ModelType.ISOLATION_FOREST:
                scores = -self.model.score_samples(X)
                threshold = self.model.offset_ if hasattr(self.model, "offset_") else 0.5
            elif self.config.model_type == ModelType.ONE_CLASS_SVM:
                scores = -self.model.decision_function(X)
                threshold = 0.0  # One-Class SVM uses 0 as threshold
            else:
                scores = np.zeros(X.shape[0])
                threshold = 0.5

            predictions = []
            for i, score in enumerate(scores):
                is_anomaly = score > threshold
                predictions.append(AnomalyPrediction(
                    model_id=self.config.model_type.value,
                    is_anomaly=bool(is_anomaly),
                    anomaly_score=float(score),
                    threshold=float(threshold),
                    features={self.config.features[j]: float(X[i, j]) for j in range(X.shape[1])},
                    timestamp=time.time(),
                ))

            return predictions

        except Exception as e:
            self.logger.error(f"Error predicting anomalies: {e}")
            return []

    def partial_fit(self, X: np.ndarray, y: Optional[np.ndarray] = None) -> ModelTrainingResult:
        """
        Perform online learning with new data.

        Note: Not all models support online learning. This method will
        retrain the model if online learning is not supported.

        Args:
            X: New training data.
            y: Target values (ignored).

        Returns:
            Training result.
        """
        if self.config.model_type == ModelType.ISOLATION_FOREST:
            # Isolation Forest doesn't support online learning, so we retrain
            return self.train(X)
        elif self.config.model_type == ModelType.ONE_CLASS_SVM:
            # One-Class SVM doesn't support online learning, so we retrain
            return self.train(X)
        else:
            return ModelTrainingResult(
                model_id=self.config.model_type.value,
                status=ModelStatus.ERROR,
                error="Online learning not supported for this model type",
            )

    def save(self, path: str) -> bool:
        """
        Save the model to disk.

        Args:
            path: Path to save the model.

        Returns:
            True if successful, False otherwise.
        """
        if not HAS_JOBLIB:
            self.logger.error("joblib not available. Cannot save model.")
            return False
            
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            joblib.dump({
                "config": self.config,
                "pipeline": self.pipeline,
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
    def load(cls, path: str) -> "AnomalyDetectionModel":
        """
        Load a model from disk.

        Args:
            path: Path to the saved model.

        Returns:
            Loaded AnomalyDetectionModel instance.
        """
        if not HAS_JOBLIB:
            logger = logging.getLogger(__name__)
            logger.error("joblib not available. Cannot load model.")
            raise ImportError("joblib not available. Cannot load model.")
            
        try:
            data = joblib.load(path)
            config = data["config"]
            model = cls(config)
            model.pipeline = data["pipeline"]
            model.model = model.pipeline.named_steps["model"]
            model.scaler = model.pipeline.named_steps["scaler"]
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
            "features": self.config.features,
            "contamination": self.config.contamination,
        }


class AnomalyModelRegistry:
    """
    Registry for managing multiple anomaly detection models.
    """

    def __init__(self):
        """Initialize the model registry."""
        self.models: Dict[str, AnomalyDetectionModel] = {}
        self.logger = logging.getLogger("AnomalyModelRegistry")

    def register_model(self, model_id: str, model: AnomalyDetectionModel) -> None:
        """Register a model."""
        self.models[model_id] = model
        self.logger.info(f"Registered model: {model_id}")

    def unregister_model(self, model_id: str) -> bool:
        """Unregister a model."""
        if model_id in self.models:
            del self.models[model_id]
            self.logger.info(f"Unregistered model: {model_id}")
            return True
        return False

    def get_model(self, model_id: str) -> Optional[AnomalyDetectionModel]:
        """Get a model by ID."""
        return self.models.get(model_id)

    def list_models(self) -> List[str]:
        """List all registered model IDs."""
        return list(self.models.keys())

    def train_model(
        self,
        model_id: str,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
    ) -> ModelTrainingResult:
        """Train a model."""
        model = self.models.get(model_id)
        if not model:
            return ModelTrainingResult(
                model_id=model_id,
                status=ModelStatus.ERROR,
                error=f"Model {model_id} not found",
            )
        return model.train(X, y)

    def predict(self, model_id: str, X: np.ndarray) -> List[AnomalyPrediction]:
        """Make predictions with a model."""
        model = self.models.get(model_id)
        if not model:
            return []
        return model.predict(X)

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
                    model = AnomalyDetectionModel.load(path)
                    self.register_model(model_id, model)
                    results[model_id] = True
                except Exception as e:
                    results[model_id] = False
                    self.logger.error(f"Error loading model {model_id}: {e}")

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        trained = sum(1 for m in self.models.values() if m.status == ModelStatus.TRAINED)
        return {
            "total_models": len(self.models),
            "trained_models": trained,
            "not_trained": len(self.models) - trained,
        }
