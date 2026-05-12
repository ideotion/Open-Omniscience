"""
Pillar 4: Real-Time Monitoring & Alerting System - Threat Classification Models

Machine learning models for threat classification.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
import joblib
import os


class ThreatModelType(Enum):
    NAIVE_BAYES = "naive_bayes"
    SVM = "svm"
    RANDOM_FOREST = "random_forest"
    BERT = "bert"  # Placeholder for future implementation


class ThreatModelStatus(Enum):
    NOT_TRAINED = "not_trained"
    TRAINING = "training"
    TRAINED = "trained"
    ERROR = "error"


@dataclass
class ThreatModelConfig:
    """Configuration for a threat classification model."""
    model_type: ThreatModelType
    n_features: int = 10000  # For text vectorization
    n_estimators: int = 100  # For Random Forest
    max_depth: Optional[int] = None  # For Random Forest
    kernel: str = "linear"  # For SVM
    C: float = 1.0  # For SVM
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreatTrainingResult:
    """Result of threat model training."""
    model_id: str
    status: ThreatModelStatus
    training_time: float
    samples_trained: int
    classes: List[str]
    error: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class ThreatPrediction:
    """Result of a threat prediction."""
    model_id: str
    text: str
    predicted_class: str
    confidence: float
    probabilities: Dict[str, float]
    timestamp: float


class ThreatClassificationModel:
    """
    Threat classification model with support for:
    - Naive Bayes
    - SVM
    - Random Forest
    - Text classification for threat detection
    """

    def __init__(self, config: ThreatModelConfig):
        """
        Initialize a threat classification model.

        Args:
            config: Model configuration.
        """
        self.config = config
        self.model = self._create_model()
        self.vectorizer = TfidfVectorizer(max_features=self.config.n_features)
        self.pipeline = Pipeline([
            ("tfidf", self.vectorizer),
            ("classifier", self.model),
        ])
        self.label_encoder = LabelEncoder()
        self.status = ThreatModelStatus.NOT_TRAINED
        self.trained_at: float = 0.0
        self.training_samples: int = 0
        self.classes: List[str] = []
        self.logger = logging.getLogger(f"ThreatClassificationModel({config.model_type.value})")

    def _create_model(self):
        """Create the appropriate model based on configuration."""
        if self.config.model_type == ThreatModelType.NAIVE_BAYES:
            return MultinomialNB()
        elif self.config.model_type == ThreatModelType.SVM:
            return SVC(
                kernel=self.config.kernel,
                C=self.config.C,
                probability=True,
                random_state=42,
            )
        elif self.config.model_type == ThreatModelType.RANDOM_FOREST:
            return RandomForestClassifier(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                random_state=42,
            )
        else:
            raise ValueError(f"Unsupported model type: {self.config.model_type}")

    def train(self, texts: List[str], labels: List[str]) -> ThreatTrainingResult:
        """
        Train the model on labeled text data.

        Args:
            texts: List of text samples.
            labels: List of corresponding labels.

        Returns:
            Training result.
        """
        start_time = time.time()
        self.status = ThreatModelStatus.TRAINING

        try:
            # Encode labels
            self.classes = list(set(labels))
            self.label_encoder.fit(self.classes)
            encoded_labels = self.label_encoder.transform(labels)

            # Train the pipeline
            self.pipeline.fit(texts, encoded_labels)

            self.status = ThreatModelStatus.TRAINED
            self.trained_at = time.time()
            self.training_samples = len(texts)

            training_time = time.time() - start_time

            # Calculate training metrics (simplified)
            if len(texts) > 1:
                # Predict on training data to get metrics (in production, use a validation set)
                predictions = self.predict(texts)
                correct = sum(1 for p, l in zip(predictions, labels) if p.predicted_class == l)
                accuracy = correct / len(texts)

                self.logger.info(
                    f"Trained {self.config.model_type.value} model on {len(texts)} samples "
                    f"with {len(self.classes)} classes in {training_time:.2f}s (accuracy: {accuracy:.4f})"
                )

                return ThreatTrainingResult(
                    model_id=self.config.model_type.value,
                    status=self.status,
                    training_time=training_time,
                    samples_trained=len(texts),
                    classes=self.classes,
                    metrics={"accuracy": float(accuracy)},
                )
            else:
                return ThreatTrainingResult(
                    model_id=self.config.model_type.value,
                    status=self.status,
                    training_time=training_time,
                    samples_trained=len(texts),
                    classes=self.classes,
                )

        except Exception as e:
            self.status = ThreatModelStatus.ERROR
            self.logger.error(f"Error training model: {e}")
            return ThreatTrainingResult(
                model_id=self.config.model_type.value,
                status=self.status,
                training_time=time.time() - start_time,
                samples_trained=0,
                classes=[],
                error=str(e),
            )

    def predict(self, texts: List[str]) -> List[ThreatPrediction]:
        """
        Predict threat classes for text samples.

        Args:
            texts: List of text samples to classify.

        Returns:
            List of threat predictions.
        """
        if self.status != ThreatModelStatus.TRAINED:
            self.logger.warning(f"Model not trained, cannot predict")
            return []

        try:
            # Get predictions
            encoded_predictions = self.pipeline.predict(texts)
            prediction_proba = self.pipeline.predict_proba(texts)

            predictions = []
            for i, (text, encoded_pred, proba) in enumerate(zip(texts, encoded_predictions, prediction_proba)):
                predicted_class = self.label_encoder.inverse_transform([encoded_pred])[0]
                confidence = float(np.max(proba))

                # Create probability dictionary
                prob_dict = {
                    self.label_encoder.inverse_transform([j])[0]: float(p)
                    for j, p in enumerate(proba)
                }

                predictions.append(ThreatPrediction(
                    model_id=self.config.model_type.value,
                    text=text,
                    predicted_class=predicted_class,
                    confidence=confidence,
                    probabilities=prob_dict,
                    timestamp=time.time(),
                ))

            return predictions

        except Exception as e:
            self.logger.error(f"Error predicting: {e}")
            return []

    def predict_single(self, text: str) -> Optional[ThreatPrediction]:
        """
        Predict threat class for a single text.

        Args:
            text: Text to classify.

        Returns:
            Threat prediction, or None if error.
        """
        predictions = self.predict([text])
        return predictions[0] if predictions else None

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
                "pipeline": self.pipeline,
                "label_encoder": self.label_encoder,
                "status": self.status,
                "trained_at": self.trained_at,
                "training_samples": self.training_samples,
                "classes": self.classes,
            }, path)
            self.logger.info(f"Model saved to {path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving model: {e}")
            return False

    @classmethod
    def load(cls, path: str) -> "ThreatClassificationModel":
        """
        Load a model from disk.

        Args:
            path: Path to the saved model.

        Returns:
            Loaded ThreatClassificationModel instance.
        """
        try:
            data = joblib.load(path)
            config = data["config"]
            model = cls(config)
            model.pipeline = data["pipeline"]
            model.model = model.pipeline.named_steps["classifier"]
            model.vectorizer = model.pipeline.named_steps["tfidf"]
            model.label_encoder = data["label_encoder"]
            model.status = data["status"]
            model.trained_at = data["trained_at"]
            model.training_samples = data["training_samples"]
            model.classes = data["classes"]
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
            "classes": self.classes,
            "n_features": self.config.n_features,
        }


class ThreatModelRegistry:
    """
    Registry for managing multiple threat classification models.
    """

    def __init__(self):
        """Initialize the model registry."""
        self.models: Dict[str, ThreatClassificationModel] = {}
        self.logger = logging.getLogger("ThreatModelRegistry")

    def register_model(self, model_id: str, model: ThreatClassificationModel) -> None:
        """Register a model."""
        self.models[model_id] = model
        self.logger.info(f"Registered threat model: {model_id}")

    def unregister_model(self, model_id: str) -> bool:
        """Unregister a model."""
        if model_id in self.models:
            del self.models[model_id]
            self.logger.info(f"Unregistered threat model: {model_id}")
            return True
        return False

    def get_model(self, model_id: str) -> Optional[ThreatClassificationModel]:
        """Get a model by ID."""
        return self.models.get(model_id)

    def list_models(self) -> List[str]:
        """List all registered model IDs."""
        return list(self.models.keys())

    def train_model(
        self,
        model_id: str,
        texts: List[str],
        labels: List[str],
    ) -> ThreatTrainingResult:
        """Train a model."""
        model = self.models.get(model_id)
        if not model:
            return ThreatTrainingResult(
                model_id=model_id,
                status=ThreatModelStatus.ERROR,
                error=f"Model {model_id} not found",
            )
        return model.train(texts, labels)

    def predict(self, model_id: str, texts: List[str]) -> List[ThreatPrediction]:
        """Make predictions with a model."""
        model = self.models.get(model_id)
        if not model:
            return []
        return model.predict(texts)

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
                    model = ThreatClassificationModel.load(path)
                    self.register_model(model_id, model)
                    results[model_id] = True
                except Exception as e:
                    results[model_id] = False
                    self.logger.error(f"Error loading threat model {model_id}: {e}")

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        trained = sum(1 for m in self.models.values() if m.status == ThreatModelStatus.TRAINED)
        return {
            "total_models": len(self.models),
            "trained_models": trained,
            "not_trained": len(self.models) - trained,
        }
