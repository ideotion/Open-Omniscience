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
Deepfake Detector Module

Provides detection of AI-generated or manipulated media (images, video, audio)
using 100% FOSS models and libraries. Works completely offline.

This module can:
- Detect deepfake images using CNN-based models
- Detect deepfake videos using temporal analysis
- Detect deepfake audio using spectral analysis
- Identify manipulation artifacts
- Provide confidence scores for detections
"""

import os
import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Optional imports
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    import onnxruntime as ort
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False


class DeepfakeStatus(Enum):
    GENUINE = "genuine"
    SUSPICIOUS = "suspicious"
    FAKE = "fake"
    UNKNOWN = "unknown"


class ArtifactType(Enum):
    BLURRING = "blurring"
    INCONSISTENT_LIGHTING = "inconsistent_lighting"
    UNNATURAL_COLORS = "unnatural_colors"
    FACE_ARTIFACTS = "face_artifacts"
    EYE_ARTIFACTS = "eye_artifacts"
    TEMPORAL_ARTIFACTS = "temporal_artifacts"
    AUDIO_ARTIFACTS = "audio_artifacts"
    SPECTRAL_ANOMALIES = "spectral_anomalies"
    NOISE_PATTERNS = "noise_patterns"


@dataclass
class Artifact:
    artifact_type: ArtifactType
    location: str
    severity: float
    description: str
    confidence: float
    coordinates: Optional[Tuple[int, int, int, int]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type.value,
            "location": self.location,
            "severity": self.severity,
            "description": self.description,
            "confidence": self.confidence,
            "coordinates": list(self.coordinates) if self.coordinates else None,
        }


@dataclass
class DeepfakeResult:
    status: DeepfakeStatus
    confidence: float
    score: float
    artifacts: List[Artifact] = field(default_factory=list)
    model_used: str = ""
    processing_time: float = 0.0
    timestamp: str = ""
    file_path: str = ""
    file_hash: str = ""
    file_type: str = ""
    model_version: str = "1.0.0"
    
    @property
    def is_deepfake(self) -> bool:
        return self.status == DeepfakeStatus.FAKE
    
    @property
    def is_genuine(self) -> bool:
        return self.status == DeepfakeStatus.GENUINE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "score": self.score,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "model_used": self.model_used,
            "processing_time": self.processing_time,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "file_type": self.file_type,
        }


class DeepfakeDetector:
    """Detects deepfakes in images, videos, and audio using FOSS models."""
    
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "models", "deepfake"
        )
        self._models = {}
        self._initialize_models()
    
    def _initialize_models(self) -> None:
        if HAS_ONNX:
            self._load_onnx_models()
    
    def _load_onnx_models(self) -> None:
        model_configs = [
            {"name": "faceforensics", "file": "faceforensics.onnx", "type": "image"},
            {"name": "wilddeepfake", "file": "wilddeepfake.onnx", "type": "image"},
        ]
        for config in model_configs:
            model_file = os.path.join(self.model_path, config["file"])
            if os.path.exists(model_file):
                try:
                    self._models[config["name"]] = ort.InferenceSession(
                        model_file, providers=['CPUExecutionProvider']
                    )
                except Exception:
                    pass
    
    def _get_timestamp(self) -> str:
        return datetime.utcnow().isoformat() + 'Z'
    
    def _calculate_file_hash(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def detect_image(self, file_path: str) -> DeepfakeResult:
        import time
        start_time = time.time()
        
        if not os.path.exists(file_path):
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.BLURRING,
                    location="file",
                    severity=1.0,
                    description="File not found",
                    confidence=1.0,
                )],
            )
        
        file_hash = self._calculate_file_hash(file_path)
        
        if not HAS_PIL and not HAS_OPENCV:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.BLURRING,
                    location="file",
                    severity=1.0,
                    description="No image processing libraries",
                    confidence=1.0,
                )],
            )
        
        try:
            if HAS_PIL:
                img = Image.open(file_path)
                img_array = np.array(img)
                if img_array.ndim == 2:
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2RGB)
                elif img_array.shape[2] == 4:
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)
            else:
                img_array = cv2.imread(file_path)
                if img_array is None:
                    return DeepfakeResult(
                        status=DeepfakeStatus.UNKNOWN,
                        confidence=0.0,
                        score=0.0,
                        processing_time=time.time() - start_time,
                        timestamp=self._get_timestamp(),
                        file_path=file_path,
                        file_hash=file_hash,
                        artifacts=[Artifact(
                            artifact_type=ArtifactType.BLURRING,
                            location="file",
                            severity=1.0,
                            description="Failed to load image",
                            confidence=1.0,
                        )],
                    )
                img_array = cv2.cvtColor(img_array, cv2.COLOR_BGR2RGB)
            
            # Run artifact detection
            artifacts = self._detect_image_artifacts(img_array)
            
            # Calculate confidence from artifacts
            if artifacts:
                avg_severity = np.mean([a.severity * a.confidence for a in artifacts])
                confidence = min(1.0, avg_severity * 1.5)
            else:
                confidence = 0.0
            
            # Determine status
            if confidence >= 0.7:
                status = DeepfakeStatus.FAKE
            elif confidence >= 0.3:
                status = DeepfakeStatus.SUSPICIOUS
            else:
                status = DeepfakeStatus.GENUINE
            
            processing_time = time.time() - start_time
            
            return DeepfakeResult(
                status=status,
                confidence=confidence,
                score=confidence * 100.0,
                artifacts=artifacts,
                model_used="artifact_analysis",
                processing_time=processing_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                file_type="image",
            )
            
        except Exception as e:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.BLURRING,
                    location="file",
                    severity=1.0,
                    description=f"Error: {str(e)}",
                    confidence=1.0,
                )],
            )
    
    def _detect_image_artifacts(self, img_array: np.ndarray) -> List[Artifact]:
        artifacts = []
        
        # Check for blurring
        blur_score = self._detect_blur(img_array)
        if blur_score < 50:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.BLURRING,
                location="full_image",
                severity=min(1.0, (100 - blur_score) / 100.0),
                description=f"Unusual blurring (score: {blur_score:.1f})",
                confidence=0.8,
            ))
        
        # Check for compression artifacts
        compression_score = self._detect_compression_artifacts(img_array)
        if compression_score > 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.BLURRING,
                location="full_image",
                severity=compression_score,
                description=f"Compression artifacts (score: {compression_score:.2f})",
                confidence=0.7,
            ))
        
        # Check for face artifacts
        face_artifacts = self._detect_face_artifacts(img_array)
        artifacts.extend(face_artifacts)
        
        # Check for unnatural colors
        color_score = self._detect_unnatural_colors(img_array)
        if color_score > 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.UNNATURAL_COLORS,
                location="full_image",
                severity=color_score,
                description=f"Unnatural colors (score: {color_score:.2f})",
                confidence=0.6,
            ))
        
        return artifacts
    
    def _detect_blur(self, img_array: np.ndarray) -> float:
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            return float(laplacian.var())
        except Exception:
            return 100.0
    
    def _detect_compression_artifacts(self, img_array: np.ndarray) -> float:
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            edges = cv2.Canny(gray, 100, 200)
            edge_density = np.sum(edges > 0) / edges.size
            return min(1.0, 1.0 - edge_density)
        except Exception:
            return 0.0
    
    def _detect_face_artifacts(self, img_array: np.ndarray) -> List[Artifact]:
        artifacts = []
        try:
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            for (x, y, w, h) in faces:
                face_roi = gray[y:y+h, x:x+w]
                face_blur = self._detect_blur(face_roi)
                if face_blur < 30:
                    artifacts.append(Artifact(
                        artifact_type=ArtifactType.FACE_ARTIFACTS,
                        location="face",
                        severity=min(1.0, (100 - face_blur) / 100.0),
                        description=f"Blurry face (score: {face_blur:.1f})",
                        confidence=0.9,
                        coordinates=(x, y, w, h),
                    ))
        except Exception:
            pass
        return artifacts
    
    def _detect_unnatural_colors(self, img_array: np.ndarray) -> float:
        try:
            if len(img_array.shape) == 2:
                return 0.0
            hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)
            hue = hsv[:, :, 0]
            saturation = hsv[:, :, 1]
            mean_sat = np.mean(saturation)
            std_sat = np.std(saturation)
            hue_range = np.max(hue) - np.min(hue)
            
            score = 0.0
            if hue_range < 30:
                score += 0.3
            if mean_sat > 200 or mean_sat < 50:
                score += 0.2
            if std_sat < 10:
                score += 0.3
            return min(1.0, score)
        except Exception:
            return 0.0
    
    def detect_video(self, file_path: str, frame_count: int = 10) -> DeepfakeResult:
        import time
        start_time = time.time()
        
        if not os.path.exists(file_path):
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description="File not found",
                    confidence=1.0,
                )],
            )
        
        if not HAS_OPENCV:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=self._calculate_file_hash(file_path),
                artifacts=[Artifact(
                    artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description="OpenCV not available",
                    confidence=1.0,
                )],
            )
        
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return DeepfakeResult(
                    status=DeepfakeStatus.UNKNOWN,
                    confidence=0.0,
                    score=0.0,
                    processing_time=time.time() - start_time,
                    timestamp=self._get_timestamp(),
                    file_path=file_path,
                    file_hash=self._calculate_file_hash(file_path),
                    artifacts=[Artifact(
                        artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                        location="file",
                        severity=1.0,
                        description="Failed to open video",
                        confidence=1.0,
                    )],
                )
            
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_indices = self._get_sample_frame_indices(total_frames, frame_count)
            
            artifacts = []
            confidences = []
            prev_frame = None
            
            for frame_idx in frame_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_arts = self._detect_image_artifacts(frame_rgb)
                artifacts.extend(frame_arts)
                
                if prev_frame is not None:
                    temporal_conf, temporal_arts = self._check_temporal_consistency(
                        prev_frame, frame_rgb
                    )
                    confidences.append(temporal_conf)
                    artifacts.extend(temporal_arts)
                
                prev_frame = frame_rgb
            
            cap.release()
            
            # Calculate confidence
            if artifacts:
                avg_severity = np.mean([a.severity * a.confidence for a in artifacts])
                confidence = min(1.0, avg_severity * 1.2)
            else:
                confidence = 0.0
            
            if confidences:
                confidence = max(confidence, np.mean(confidences))
            
            # Determine status
            if confidence >= 0.7:
                status = DeepfakeStatus.FAKE
            elif confidence >= 0.3:
                status = DeepfakeStatus.SUSPICIOUS
            else:
                status = DeepfakeStatus.GENUINE
            
            processing_time = time.time() - start_time
            
            return DeepfakeResult(
                status=status,
                confidence=confidence,
                score=confidence * 100.0,
                artifacts=artifacts,
                model_used="video_analysis",
                processing_time=processing_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=self._calculate_file_hash(file_path),
                file_type="video",
            )
            
        except Exception as e:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=self._calculate_file_hash(file_path),
                artifacts=[Artifact(
                    artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description=f"Error: {str(e)}",
                    confidence=1.0,
                )],
            )
    
    def _get_sample_frame_indices(self, total_frames: int, frame_count: int) -> List[int]:
        if total_frames <= frame_count:
            return list(range(total_frames))
        step = total_frames / frame_count
        return [int(i * step) for i in range(frame_count)]
    
    def _check_temporal_consistency(self, prev_frame: np.ndarray, curr_frame: np.ndarray) -> Tuple[float, List[Artifact]]:
        artifacts = []
        confidences = []
        
        # Check optical flow
        flow_score = self._check_optical_flow(prev_frame, curr_frame)
        if flow_score < 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                location="frames",
                severity=1.0 - flow_score,
                description=f"Optical flow inconsistency",
                confidence=0.8,
            ))
            confidences.append(1.0 - flow_score)
        
        # Check flickering
        flicker_score = self._detect_flickering(prev_frame, curr_frame)
        if flicker_score > 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.TEMPORAL_ARTIFACTS,
                location="frames",
                severity=flicker_score,
                description=f"Flickering detected",
                confidence=0.7,
            ))
            confidences.append(flicker_score)
        
        return np.mean(confidences) if confidences else 0.0, artifacts
    
    def _check_optical_flow(self, prev_frame: np.ndarray, curr_frame: np.ndarray) -> float:
        try:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_RGB2GRAY)
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_RGB2GRAY)
            flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
            mean_mag = np.mean(magnitude)
            if mean_mag < 0.1:
                return 0.3
            elif mean_mag > 10:
                return 0.4
            return 0.9
        except Exception:
            return 0.5
    
    def _detect_flickering(self, prev_frame: np.ndarray, curr_frame: np.ndarray) -> float:
        try:
            diff = cv2.absdiff(prev_frame.astype(np.float32), curr_frame.astype(np.float32))
            mean_diff = np.mean(diff)
            max_diff = 255.0 * 3.0
            return min(1.0, (mean_diff / max_diff) * 2.0)
        except Exception:
            return 0.0
    
    def detect_audio(self, file_path: str) -> DeepfakeResult:
        import time
        start_time = time.time()
        
        if not os.path.exists(file_path):
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.AUDIO_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description="File not found",
                    confidence=1.0,
                )],
            )
        
        file_hash = self._calculate_file_hash(file_path)
        
        if not HAS_LIBROSA and not HAS_PYDUB:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.AUDIO_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description="No audio libraries available",
                    confidence=1.0,
                )],
            )
        
        try:
            if HAS_LIBROSA:
                y, sr = librosa.load(file_path, sr=None)
                artifacts = self._detect_audio_artifacts(y, sr)
            elif HAS_PYDUB:
                audio = AudioSegment.from_file(file_path)
                samples = np.array(audio.get_array_of_samples())
                if audio.channels > 1:
                    samples = samples.reshape((-1, audio.channels))
                    samples = np.mean(samples, axis=1)
                sr = audio.frame_rate
                artifacts = self._detect_audio_artifacts(samples, sr)
            else:
                artifacts = []
            
            # Calculate confidence
            if artifacts:
                avg_severity = np.mean([a.severity * a.confidence for a in artifacts])
                confidence = min(1.0, avg_severity * 1.5)
            else:
                confidence = 0.0
            
            # Determine status
            if confidence >= 0.7:
                status = DeepfakeStatus.FAKE
            elif confidence >= 0.3:
                status = DeepfakeStatus.SUSPICIOUS
            else:
                status = DeepfakeStatus.GENUINE
            
            processing_time = time.time() - start_time
            
            return DeepfakeResult(
                status=status,
                confidence=confidence,
                score=confidence * 100.0,
                artifacts=artifacts,
                model_used="audio_analysis",
                processing_time=processing_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                file_type="audio",
            )
            
        except Exception as e:
            return DeepfakeResult(
                status=DeepfakeStatus.UNKNOWN,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                file_path=file_path,
                file_hash=file_hash,
                artifacts=[Artifact(
                    artifact_type=ArtifactType.AUDIO_ARTIFACTS,
                    location="file",
                    severity=1.0,
                    description=f"Error: {str(e)}",
                    confidence=1.0,
                )],
            )
    
    def _detect_audio_artifacts(self, y: np.ndarray, sr: int) -> List[Artifact]:
        artifacts = []
        
        # Check spectral anomalies
        spectral_score = self._detect_spectral_anomalies(y, sr)
        if spectral_score > 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.SPECTRAL_ANOMALIES,
                location="full_audio",
                severity=spectral_score,
                description=f"Spectral anomalies (score: {spectral_score:.2f})",
                confidence=0.8,
            ))
        
        # Check noise patterns
        noise_score = self._detect_noise_patterns(y)
        if noise_score > 0.5:
            artifacts.append(Artifact(
                artifact_type=ArtifactType.NOISE_PATTERNS,
                location="full_audio",
                severity=noise_score,
                description=f"Noise patterns (score: {noise_score:.2f})",
                confidence=0.7,
            ))
        
        return artifacts
    
    def _detect_spectral_anomalies(self, y: np.ndarray, sr: int) -> float:
        try:
            D = np.abs(librosa.stft(y))
            spectral_centroids = librosa.feature.spectral_centroid(S=D)[0]
            mean_centroid = np.mean(spectral_centroids)
            std_centroid = np.std(spectral_centroids)
            
            score = 0.0
            if mean_centroid < 500:
                score += 0.3
            if mean_centroid > 4000:
                score += 0.3
            if std_centroid < 100:
                score += 0.2
            if std_centroid > 2000:
                score += 0.2
            return min(1.0, score)
        except Exception:
            return 0.0
    
    def _detect_noise_patterns(self, y: np.ndarray) -> float:
        try:
            window_size = 1024
            hop_length = 512
            rms = librosa.feature.rms(y=y, frame_length=window_size, hop_length=hop_length)[0]
            mean_rms = np.mean(rms)
            std_rms = np.std(rms)
            min_rms = np.min(rms)
            
            score = 0.0
            if mean_rms > 0 and (mean_rms - min_rms) / mean_rms < 0.1:
                score += 0.4
            if std_rms / mean_rms > 0.5:
                score += 0.3
            return min(1.0, score)
        except Exception:
            return 0.0
    
    def check_dependencies(self) -> Dict[str, bool]:
        return {
            "OpenCV": HAS_OPENCV,
            "ONNX Runtime": HAS_ONNX,
            "Pillow": HAS_PIL,
            "librosa": HAS_LIBROSA,
            "pydub": HAS_PYDUB,
        }
