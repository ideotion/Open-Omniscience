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
Multi-Modal Analysis Module

Provides cross-modal verification and consistency checking for multi-media content.
Uses 100% FOSS libraries for offline text, image, audio, and video analysis.

This module can:
- Extract text from images using OCR (Tesseract)
- Compare text content with image content
- Check semantic consistency across modalities
- Validate audio-video synchronization
- Detect cross-modal inconsistencies
"""

import os
import json
import hashlib
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

# Optional imports
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

try:
    import spacy
    HAS_SPACY = True
    # Try to load English model
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        HAS_SPACY = False
except ImportError:
    HAS_SPACY = False


class MediaType(Enum):
    """Types of media supported for multi-modal analysis."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"
    UNKNOWN = "unknown"


class ConsistencyStatus(Enum):
    """Status of cross-modal consistency."""
    CONSISTENT = "consistent"
    PARTIALLY_CONSISTENT = "partially_consistent"
    INCONSISTENT = "inconsistent"
    UNRELATED = "unrelated"
    ERROR = "error"


@dataclass
class MediaItem:
    """Represents a single media item for analysis."""
    file_path: str
    media_type: MediaType
    content: Optional[Any] = None  # Raw content (image array, audio data, text)
    metadata: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + 'Z'


@dataclass
class SemanticComparison:
    """Result of semantic comparison between two media items."""
    media1_path: str
    media2_path: str
    similarity_score: float  # 0.0 to 1.0
    semantic_distance: float  # 0.0 to infinity (lower is more similar)
    matching_concepts: List[str] = field(default_factory=list)
    conflicting_concepts: List[str] = field(default_factory=list)
    confidence: float = 1.0
    method: str = ""


@dataclass
class CrossModalResult:
    """Result of cross-modal analysis."""
    consistency_status: ConsistencyStatus
    overall_score: float  # 0.0 to 100.0
    semantic_comparisons: List[SemanticComparison] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    confidence: float = 1.0
    processing_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "consistency_status": self.consistency_status.value,
            "overall_score": self.overall_score,
            "semantic_comparisons": [
                {
                    "media1_path": sc.media1_path,
                    "media2_path": sc.media2_path,
                    "similarity_score": sc.similarity_score,
                    "semantic_distance": sc.semantic_distance,
                    "matching_concepts": sc.matching_concepts,
                    "conflicting_concepts": sc.conflicting_concepts,
                    "confidence": sc.confidence,
                    "method": sc.method,
                }
                for sc in self.semantic_comparisons
            ],
            "issues": self.issues,
            "confidence": self.confidence,
            "processing_time": self.processing_time,
        }


@dataclass
class MultiModalResult:
    """Complete result of multi-modal analysis."""
    consistency_score: float  # 0.0 to 100.0
    individual_results: Dict[MediaType, Any] = field(default_factory=dict)
    cross_modal_analysis: CrossModalResult = field(default_factory=lambda: CrossModalResult(
        consistency_status=ConsistencyStatus.ERROR,
        overall_score=0.0
    ))
    detected_artifacts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    processing_time: float = 0.0
    model_version: str = "1.0.0"
    
    @property
    def is_consistent(self) -> bool:
        """Check if multi-modal content is consistent."""
        return self.consistency_score >= 80.0
    
    @property
    def has_issues(self) -> bool:
        """Check if there are any issues."""
        return len(self.cross_modal_analysis.issues) > 0 or len(self.detected_artifacts) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "consistency_score": self.consistency_score,
            "individual_results": {
                mt.value: result.to_dict() if hasattr(result, 'to_dict') else result
                for mt, result in self.individual_results.items()
            },
            "cross_modal_analysis": self.cross_modal_analysis.to_dict(),
            "detected_artifacts": self.detected_artifacts,
            "recommendations": self.recommendations,
            "processing_time": self.processing_time,
            "model_version": self.model_version,
            "is_consistent": self.is_consistent,
            "has_issues": self.has_issues,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class MultiModalAnalyzer:
    """
    Performs multi-modal analysis across text, images, audio, and video.
    
    This class provides comprehensive cross-modal verification using 100% FOSS
    libraries. It can detect inconsistencies between different media types
    that might indicate manipulation or deception.
    
    Example usage:
        analyzer = MultiModalAnalyzer()
        
        # Analyze a set of media files
        media_files = ["image.jpg", "audio.mp3", "video.mp4"]
        result = analyzer.analyze(media_files)
        
        print(f"Consistency score: {result.consistency_score:.1f}/100")
        print(f"Is consistent: {result.is_consistent}")
        
        # Analyze text-image consistency
        text = "A beautiful sunset over the ocean"
        image_path = "sunset.jpg"
        consistency = analyzer.check_text_image_consistency(text, image_path)
        print(f"Text-image consistency: {consistency.overall_score:.1f}/100")
    """
    
    def __init__(self):
        """Initialize the multi-modal analyzer."""
        self._initialize_nlp()
    
    def _initialize_nlp(self) -> None:
        """Initialize NLP models if available."""
        self.nlp = None
        if HAS_SPACY:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                # Model not available, but spacy is installed
                pass
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat() + 'Z'
    
    # ==================== MAIN ANALYSIS METHODS ====================
    
    def analyze(self, media_paths: List[str]) -> MultiModalResult:
        """
        Analyze multiple media files for cross-modal consistency.
        
        Args:
            media_paths: List of paths to media files (images, audio, video, text)
            
        Returns:
            MultiModalResult with comprehensive analysis
        """
        import time
        start_time = time.time()
        
        if not media_paths:
            return MultiModalResult(
                consistency_score=0.0,
                cross_modal_analysis=CrossModalResult(
                    consistency_status=ConsistencyStatus.ERROR,
                    overall_score=0.0,
                    issues=["No media paths provided"],
                ),
                processing_time=time.time() - start_time,
            )
        
        # Load and process each media file
        media_items = []
        individual_results = {}
        
        for path in media_paths:
            media_type = self._determine_media_type(path)
            
            if media_type == MediaType.IMAGE:
                result = self._process_image(path)
                individual_results[MediaType.IMAGE] = result
            elif media_type == MediaType.AUDIO:
                result = self._process_audio(path)
                individual_results[MediaType.AUDIO] = result
            elif media_type == MediaType.VIDEO:
                result = self._process_video(path)
                individual_results[MediaType.VIDEO] = result
            elif media_type == MediaType.TEXT:
                result = self._process_text(path)
                individual_results[MediaType.TEXT] = result
            
            media_items.append(MediaItem(
                file_path=path,
                media_type=media_type,
                metadata=result.get('metadata', {}),
                features=result.get('features', {}),
            ))
        
        # Perform cross-modal analysis
        cross_result = self._perform_cross_modal_analysis(media_items)
        
        # Calculate overall consistency score
        consistency_score = self._calculate_consistency_score(
            individual_results, cross_result
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(cross_result, consistency_score)
        
        processing_time = time.time() - start_time
        
        return MultiModalResult(
            consistency_score=consistency_score,
            individual_results=individual_results,
            cross_modal_analysis=cross_result,
            recommendations=recommendations,
            processing_time=processing_time,
        )
    
    def _determine_media_type(self, file_path: str) -> MediaType:
        """Determine media type based on file extension."""
        ext = os.path.splitext(file_path)[1].lower()
        
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
        audio_exts = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a']
        video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
        text_exts = ['.txt', '.md', '.csv', '.json', '.xml']
        
        if ext in image_exts:
            return MediaType.IMAGE
        elif ext in audio_exts:
            return MediaType.AUDIO
        elif ext in video_exts:
            return MediaType.VIDEO
        elif ext in text_exts:
            return MediaType.TEXT
        else:
            return MediaType.UNKNOWN
    
    # ==================== MEDIA PROCESSING METHODS ====================
    
    def _process_image(self, file_path: str) -> Dict[str, Any]:
        """Process an image file and extract features."""
        result = {
            'metadata': {},
            'features': {},
            'content_type': 'image',
        }
        
        if not HAS_PIL and not HAS_OPENCV:
            result['error'] = "No image processing libraries available"
            return result
        
        try:
            # Extract text using OCR if available
            if HAS_TESSERACT and HAS_PIL:
                try:
                    img = Image.open(file_path)
                    text = pytesseract.image_to_string(img)
                    result['features']['extracted_text'] = text.strip()
                    result['features']['text_length'] = len(text)
                except Exception as e:
                    result['warnings'] = [f"OCR failed: {str(e)}"]
            
            # Extract basic image features
            if HAS_PIL:
                try:
                    with Image.open(file_path) as img:
                        result['metadata'] = {
                            'format': img.format,
                            'mode': img.mode,
                            'size': {'width': img.width, 'height': img.height},
                            'aspect_ratio': img.width / img.height if img.height > 0 else 0,
                        }
                        
                        # Color analysis
                        if img.mode == 'RGB':
                            colors = self._analyze_colors(img)
                            result['features']['color_analysis'] = colors
                            
                except Exception as e:
                    result['error'] = f"Image processing failed: {str(e)}"
            
            elif HAS_OPENCV:
                try:
                    img = cv2.imread(file_path)
                    if img is not None:
                        height, width, channels = img.shape
                        result['metadata'] = {
                            'format': 'OpenCV',
                            'size': {'width': width, 'height': height},
                            'channels': channels,
                            'aspect_ratio': width / height if height > 0 else 0,
                        }
                        
                        # Color analysis with OpenCV
                        colors = self._analyze_colors_opencv(img)
                        result['features']['color_analysis'] = colors
                        
                except Exception as e:
                    result['error'] = f"OpenCV processing failed: {str(e)}"
            
        except Exception as e:
            result['error'] = f"Failed to process image: {str(e)}"
        
        return result
    
    def _process_audio(self, file_path: str) -> Dict[str, Any]:
        """Process an audio file and extract features."""
        result = {
            'metadata': {},
            'features': {},
            'content_type': 'audio',
        }
        
        if not HAS_PYDUB and not HAS_LIBROSA:
            result['error'] = "No audio processing libraries available"
            return result
        
        try:
            if HAS_PYDUB:
                try:
                    audio = AudioSegment.from_file(file_path)
                    result['metadata'] = {
                        'duration_seconds': len(audio) / 1000.0,
                        'sample_width': audio.sample_width,
                        'frame_rate': audio.frame_rate,
                        'channels': audio.channels,
                    }
                    
                    # Extract audio features
                    features = self._extract_audio_features(audio)
                    result['features'].update(features)
                    
                except Exception as e:
                    result['error'] = f"pydub processing failed: {str(e)}"
            
            elif HAS_LIBROSA:
                try:
                    y, sr = librosa.load(file_path, sr=None)
                    result['metadata'] = {
                        'duration_seconds': len(y) / sr,
                        'sample_rate': sr,
                    }
                    
                    # Extract features with librosa
                    features = self._extract_librosa_features(y, sr)
                    result['features'].update(features)
                    
                except Exception as e:
                    result['error'] = f"librosa processing failed: {str(e)}"
            
        except Exception as e:
            result['error'] = f"Failed to process audio: {str(e)}"
        
        return result
    
    def _process_video(self, file_path: str) -> Dict[str, Any]:
        """Process a video file and extract features."""
        result = {
            'metadata': {},
            'features': {},
            'content_type': 'video',
        }
        
        if not HAS_OPENCV:
            result['error'] = "OpenCV not available for video processing"
            return result
        
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                result['error'] = "Failed to open video file"
                return result
            
            # Get video metadata
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration = frame_count / fps if fps > 0 else 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            result['metadata'] = {
                'frame_count': frame_count,
                'fps': fps,
                'duration_seconds': duration,
                'frame_width': width,
                'frame_height': height,
                'aspect_ratio': width / height if height > 0 else 0,
            }
            
            # Extract features from first frame
            ret, frame = cap.read()
            if ret:
                frame_features = self._extract_frame_features(frame)
                result['features']['first_frame'] = frame_features
            
            # Extract features from middle frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
            ret, frame = cap.read()
            if ret:
                frame_features = self._extract_frame_features(frame)
                result['features']['middle_frame'] = frame_features
            
            cap.release()
            
        except Exception as e:
            result['error'] = f"Failed to process video: {str(e)}"
        
        return result
    
    def _process_text(self, file_path: str) -> Dict[str, Any]:
        """Process a text file and extract features."""
        result = {
            'metadata': {},
            'features': {},
            'content_type': 'text',
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            result['metadata'] = {
                'file_size': os.path.getsize(file_path),
                'character_count': len(text),
                'line_count': len(text.splitlines()),
            }
            
            # Extract text features
            features = self._extract_text_features(text)
            result['features'].update(features)
            
        except Exception as e:
            result['error'] = f"Failed to process text: {str(e)}"
        
        return result
    
    # ==================== FEATURE EXTRACTION METHODS ====================
    
    def _analyze_colors(self, img) -> Dict[str, Any]:
        """Analyze colors in a PIL image."""
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Get color histogram
        colors = {}
        try:
            # Sample colors (simplified approach)
            width, height = img.size
            sample_size = min(100, width, height)
            
            # Sample from center
            left = (width - sample_size) // 2
            top = (height - sample_size) // 2
            right = left + sample_size
            bottom = top + sample_size
            
            cropped = img.crop((left, top, right, bottom))
            
            # Get dominant colors (simplified)
            color_counts = {}
            for pixel in cropped.getdata():
                color = pixel[:3]  # RGB only
                color_hex = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
                color_counts[color_hex] = color_counts.get(color_hex, 0) + 1
            
            # Get top 5 colors
            sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            colors['dominant_colors'] = [c[0] for c in sorted_colors]
            colors['color_distribution'] = {c[0]: c[1] for c in sorted_colors}
            
            # Calculate average brightness
            brightness = sum(sum(pixel[:3]) / 3 for pixel in cropped.getdata()) / (sample_size * sample_size)
            colors['average_brightness'] = brightness
            
        except Exception:
            pass
        
        return colors
    
    def _analyze_colors_opencv(self, img: np.ndarray) -> Dict[str, Any]:
        """Analyze colors in an OpenCV image."""
        colors = {}
        
        try:
            # Convert to RGB if needed
            if len(img.shape) == 3 and img.shape[2] == 3:
                # Already RGB or BGR
                pass
            elif len(img.shape) == 2:
                # Grayscale
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            else:
                return colors
            
            # Convert BGR to RGB if needed
            if img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # Get color histogram
            hist_size = 8  # Number of bins per channel
            ranges = [0, 256]
            
            hist = cv2.calcHist(
                [img],
                [0, 1, 2],
                None,
                [hist_size, hist_size, hist_size],
                ranges
            )
            
            # Normalize histogram
            hist = cv2.normalize(hist, hist).flatten()
            
            colors['color_histogram'] = hist.tolist()
            
            # Calculate average brightness
            brightness = np.mean(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY))
            colors['average_brightness'] = float(brightness)
            
            # Calculate colorfulness
            # Convert to Lab color space
            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            
            # Standard deviation of a and b channels
            std_a = np.std(a)
            std_b = np.std(b)
            mean_a = np.mean(a)
            mean_b = np.mean(b)
            
            colorfulness = np.sqrt(std_a**2 + std_b**2) + 0.3 * np.sqrt(mean_a**2 + mean_b**2)
            colors['colorfulness'] = float(colorfulness)
            
        except Exception:
            pass
        
        return colors
    
    def _extract_audio_features(self, audio: Any) -> Dict[str, Any]:
        """Extract features from audio using pydub."""
        features = {}
        
        try:
            # Get raw samples
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels > 1:
                # Convert stereo to mono by averaging channels
                samples = samples.reshape((-1, audio.channels))
                samples = np.mean(samples, axis=1)
            
            # Calculate basic statistics
            features[x27rmsx27] = float(np.sqrt(np.mean(samples**2)))
            features['max_amplitude'] = float(np.max(np.abs(samples)))
            features['mean_amplitude'] = float(np.mean(np.abs(samples)))
            
            # Zero crossing rate
            zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / 2
            features['zero_crossing_rate'] = float(zero_crossings / len(samples))
            
            # Spectral features (simplified)
            fft_result = np.fft.rfft(samples)
            magnitudes = np.abs(fft_result)
            
            # Spectral centroid
            freq_bins = np.fft.rfftfreq(len(samples), 1.0 / audio.frame_rate)
            spectral_centroid = np.sum(freq_bins * magnitudes) / np.sum(magnitudes)
            features['spectral_centroid'] = float(spectral_centroid)
            
        except Exception:
            pass
        
        return features
    
    def _extract_librosa_features(self, y: np.ndarray, sr: int) -> Dict[str, Any]:
        """Extract features from audio using librosa."""
        features = {}
        
        try:
            # RMS
            rms = librosa.feature.rms(y=y)[0]
            features['rms_mean'] = float(np.mean(rms))
            features['rms_std'] = float(np.std(rms))
            
            # Zero crossing rate
            zcr = librosa.feature.zero_crossing_rate(y)[0]
            features['zero_crossing_rate'] = float(np.mean(zcr))
            
            # Spectral centroid
            spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            features['spectral_centroid_mean'] = float(np.mean(spectral_centroids))
            
            # Spectral bandwidth
            spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
            features['spectral_bandwidth_mean'] = float(np.mean(spectral_bandwidth))
            
            # Spectral rolloff
            spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
            features['spectral_rolloff_mean'] = float(np.mean(spectral_rolloff))
            
            # MFCCs (first 13 coefficients)
            mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            for i in range(13):
                features[f'mfcc_{i+1}'] = float(np.mean(mfccs[i]))
            
        except Exception:
            pass
        
        return features
    
    def _extract_frame_features(self, frame: np.ndarray) -> Dict[str, Any]:
        """Extract features from a video frame."""
        features = {}
        
        try:
            # Convert to grayscale
            if len(frame.shape) == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray = frame
            
            # Calculate basic statistics
            features['mean_intensity'] = float(np.mean(gray))
            features['std_intensity'] = float(np.std(gray))
            features['min_intensity'] = float(np.min(gray))
            features['max_intensity'] = float(np.max(gray))
            
            # Edge detection
            edges = cv2.Canny(gray, 100, 200)
            features['edge_density'] = float(np.sum(edges > 0) / edges.size)
            
            # Blur detection (Laplacian variance)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            features['blur_score'] = float(np.var(laplacian))
            
            # Color analysis if color image
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                color_features = self._analyze_colors_opencv(frame)
                features.update(color_features)
            
        except Exception:
            pass
        
        return features
    
    def _extract_text_features(self, text: str) -> Dict[str, Any]:
        """Extract features from text."""
        features = {}
        
        try:
            # Basic statistics
            features['character_count'] = len(text)
            features['word_count'] = len(text.split())
            features['sentence_count'] = len(text.split('. '))
            features['line_count'] = len(text.splitlines())
            
            # Average word length
            words = text.split()
            if words:
                avg_word_length = sum(len(word) for word in words) / len(words)
                features['avg_word_length'] = avg_word_length
            
            # Unique word ratio
            unique_words = set(word.lower() for word in words)
            if words:
                features['unique_word_ratio'] = len(unique_words) / len(words)
            
            # Sentiment analysis (if VADER is available)
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                analyzer = SentimentIntensityAnalyzer()
                sentiment = analyzer.polarity_scores(text)
                features['sentiment'] = sentiment
            except ImportError:
                pass
            
            # NLP features (if spaCy is available)
            if self.nlp and text:
                try:
                    doc = self.nlp(text[:1000000])  # Limit to 1M characters
                    
                    # Named entities
                    entities = [(ent.text, ent.label_) for ent in doc.ents]
                    features['named_entities'] = [e[0] for e in entities]
                    features['entity_types'] = list(set(e[1] for e in entities))
                    
                    # Part-of-speech tags
                    pos_counts = {}
                    for token in doc:
                        pos = token.pos_
                        pos_counts[pos] = pos_counts.get(pos, 0) + 1
                    features['pos_distribution'] = pos_counts
                    
                    # Nouns, verbs, adjectives
                    features['noun_count'] = sum(1 for token in doc if token.pos_ == 'NOUN')
                    features['verb_count'] = sum(1 for token in doc if token.pos_ == 'VERB')
                    features['adj_count'] = sum(1 for token in doc if token.pos_ == 'ADJ')
                    
                except Exception:
                    pass
            
        except Exception:
            pass
        
        return features
    
    # ==================== CROSS-MODAL ANALYSIS METHODS ====================
    
    def _perform_cross_modal_analysis(self, media_items: List[MediaItem]) -> CrossModalResult:
        """Perform cross-modal analysis on multiple media items."""
        import time
        start_time = time.time()
        
        semantic_comparisons = []
        issues = []
        
        # Compare each pair of media items
        for i in range(len(media_items)):
            for j in range(i + 1, len(media_items)):
                item1 = media_items[i]
                item2 = media_items[j]
                
                # Perform semantic comparison
                comparison = self._compare_media_items(item1, item2)
                semantic_comparisons.append(comparison)
                
                # Check for issues
                if comparison.similarity_score < 0.3:
                    issues.append(
                        f"Low semantic similarity ({comparison.similarity_score:.2f}) "
                        f"between {item1.file_path} and {item2.file_path}"
                    )
        
        # Determine overall consistency status
        if not semantic_comparisons:
            status = ConsistencyStatus.ERROR
            overall_score = 0.0
        else:
            avg_similarity = np.mean([c.similarity_score for c in semantic_comparisons])
            
            if avg_similarity >= 0.7:
                status = ConsistencyStatus.CONSISTENT
            elif avg_similarity >= 0.4:
                status = ConsistencyStatus.PARTIALLY_CONSISTENT
            elif avg_similarity >= 0.2:
                status = ConsistencyStatus.INCONSISTENT
            else:
                status = ConsistencyStatus.UNRELATED
            
            overall_score = avg_similarity * 100.0
        
        processing_time = time.time() - start_time
        
        return CrossModalResult(
            consistency_status=status,
            overall_score=overall_score,
            semantic_comparisons=semantic_comparisons,
            issues=issues,
            processing_time=processing_time,
        )
    
    def _compare_media_items(self, item1: MediaItem, item2: MediaItem) -> SemanticComparison:
        """Compare two media items for semantic similarity."""
        # Try different comparison methods based on media types
        
        # Method 1: Text-based comparison (if both have text)
        text1 = item1.features.get('extracted_text', '')
        text2 = item2.features.get('extracted_text', '')
        
        if text1 and text2:
            similarity = self._compare_texts(text1, text2)
            return SemanticComparison(
                media1_path=item1.file_path,
                media2_path=item2.file_path,
                similarity_score=similarity,
                semantic_distance=1.0 - similarity,
                method="text_comparison",
                confidence=0.9,
            )
        
        # Method 2: Feature-based comparison
        features1 = item1.features
        features2 = item2.features
        
        if features1 and features2:
            similarity = self._compare_features(features1, features2)
            return SemanticComparison(
                media1_path=item1.file_path,
                media2_path=item2.file_path,
                similarity_score=similarity,
                semantic_distance=1.0 - similarity,
                method="feature_comparison",
                confidence=0.7,
            )
        
        # Method 3: Metadata-based comparison
        metadata1 = item1.metadata
        metadata2 = item2.metadata
        
        if metadata1 and metadata2:
            similarity = self._compare_metadata(metadata1, metadata2)
            return SemanticComparison(
                media1_path=item1.file_path,
                media2_path=item2.file_path,
                similarity_score=similarity,
                semantic_distance=1.0 - similarity,
                method="metadata_comparison",
                confidence=0.5,
            )
        
        # Default: no comparison possible
        return SemanticComparison(
            media1_path=item1.file_path,
            media2_path=item2.file_path,
            similarity_score=0.0,
            semantic_distance=1.0,
            method="none",
            confidence=0.0,
        )
    
    def _compare_texts(self, text1: str, text2: str) -> float:
        """Compare two texts for semantic similarity."""
        # Simple approach: use Jaccard similarity on words
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        if union == 0:
            return 0.0
        
        jaccard = intersection / union
        
        # If spaCy is available, use sentence similarity
        if self.nlp:
            try:
                doc1 = self.nlp(text1[:1000000])  # Limit length
                doc2 = self.nlp(text2[:1000000])
                similarity = doc1.similarity(doc2)
                # Combine with Jaccard
                return (jaccard + similarity) / 2.0
            except Exception:
                pass
        
        return jaccard
    
    def _compare_features(self, features1: Dict[str, Any], features2: Dict[str, Any]) -> float:
        """Compare two feature dictionaries for similarity."""
        # Find common keys
        common_keys = set(features1.keys()) & set(features2.keys())
        
        if not common_keys:
            return 0.0
        
        # Calculate similarity for each common feature
        similarities = []
        
        for key in common_keys:
            val1 = features1[key]
            val2 = features2[key]
            
            # Handle different types
            if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                # Normalize and compare
                if val1 == 0 and val2 == 0:
                    similarity = 1.0
                elif val1 == 0 or val2 == 0:
                    similarity = 0.0
                else:
                    # Use relative difference
                    diff = abs(val1 - val2) / max(abs(val1), abs(val2))
                    similarity = 1.0 - min(diff, 1.0)
                similarities.append(similarity)
            
            elif isinstance(val1, str) and isinstance(val2, str):
                # Text similarity
                similarity = self._compare_texts(val1, val2)
                similarities.append(similarity)
            
            elif isinstance(val1, list) and isinstance(val2, list):
                # List similarity (Jaccard)
                set1 = set(str(x) for x in val1)
                set2 = set(str(x) for x in val2)
                if set1 and set2:
                    intersection = len(set1 & set2)
                    union = len(set1 | set2)
                    similarity = intersection / union if union > 0 else 0.0
                    similarities.append(similarity)
            
            elif isinstance(val1, dict) and isinstance(val2, dict):
                # Recursive comparison
                similarity = self._compare_features(val1, val2)
                similarities.append(similarity)
        
        if not similarities:
            return 0.0
        
        return np.mean(similarities)
    
    def _compare_metadata(self, metadata1: Dict[str, Any], metadata2: Dict[str, Any]) -> float:
        """Compare two metadata dictionaries for similarity."""
        # Similar to feature comparison but with different weights
        common_keys = set(metadata1.keys()) & set(metadata2.keys())
        
        if not common_keys:
            return 0.0
        
        similarities = []
        
        for key in common_keys:
            val1 = metadata1[key]
            val2 = metadata2[key]
            
            # For metadata, we want exact matches for most fields
            if val1 == val2:
                similarities.append(1.0)
            elif isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                # Allow some tolerance for numeric values
                if abs(val1 - val2) / max(abs(val1), abs(val2), 1.0) < 0.01:
                    similarities.append(1.0)
                else:
                    similarities.append(0.0)
            else:
                similarities.append(0.0)
        
        if not similarities:
            return 0.0
        
        return np.mean(similarities)
    
    def _calculate_consistency_score(
        self, 
        individual_results: Dict[MediaType, Any], 
        cross_result: CrossModalResult
    ) -> float:
        """Calculate overall consistency score from individual and cross-modal results."""
        # Start with cross-modal score
        score = cross_result.overall_score
        
        # Adjust based on individual result quality
        if individual_results:
            # Check if individual results have errors
            error_count = sum(
                1 for result in individual_results.values() 
                if result.get('error')
            )
            
            # Penalize for errors
            if error_count > 0:
                penalty = (error_count / len(individual_results)) * 20.0
                score = max(0, score - penalty)
        
        # Ensure score is within bounds
        return max(0, min(100, score))
    
    def _generate_recommendations(
        self, 
        cross_result: CrossModalResult, 
        consistency_score: float
    ) -> List[str]:
        """Generate recommendations based on analysis results."""
        recommendations = []
        
        if consistency_score >= 80:
            recommendations.append(
                "✅ Multi-modal content appears consistent and genuine"
            )
        elif consistency_score >= 60:
            recommendations.append(
                "⚠️ Multi-modal content shows some inconsistencies - manual review recommended"
            )
        else:
            recommendations.append(
                "❌ Multi-modal content shows significant inconsistencies - likely manipulated"
            )
        
        # Add specific recommendations based on issues
        for issue in cross_result.issues:
            if "low semantic similarity" in issue.lower():
                recommendations.append(
                    "🔍 Investigate why the content has low semantic similarity"
                )
        
        return recommendations
    
    # ==================== SPECIALIZED CONSISTENCY CHECKS ====================
    
    def check_text_image_consistency(self, text: str, image_path: str) -> MultiModalResult:
        """
        Check consistency between text and an image.
        
        Args:
            text: Text content to compare
            image_path: Path to image file
            
        Returns:
            MultiModalResult with consistency analysis
        """
        import time
        start_time = time.time()
        
        # Process text
        text_features = self._extract_text_features(text)
        
        # Process image
        image_result = self._process_image(image_path)
        
        # Create media items
        text_item = MediaItem(
            file_path="text_input",
            media_type=MediaType.TEXT,
            content=text,
            features=text_features,
        )
        
        image_item = MediaItem(
            file_path=image_path,
            media_type=MediaType.IMAGE,
            features=image_result.get('features', {}),
            metadata=image_result.get('metadata', {}),
        )
        
        # Perform cross-modal analysis
        cross_result = self._perform_cross_modal_analysis([text_item, image_item])
        
        # Calculate consistency score
        consistency_score = self._calculate_consistency_score(
            {MediaType.TEXT: text_features, MediaType.IMAGE: image_result},
            cross_result
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(cross_result, consistency_score)
        
        processing_time = time.time() - start_time
        
        return MultiModalResult(
            consistency_score=consistency_score,
            individual_results={
                MediaType.TEXT: text_features,
                MediaType.IMAGE: image_result,
            },
            cross_modal_analysis=cross_result,
            recommendations=recommendations,
            processing_time=processing_time,
        )
    
    def check_audio_video_sync(self, audio_path: str, video_path: str) -> MultiModalResult:
        """
        Check if audio and video are properly synchronized.
        
        Args:
            audio_path: Path to audio file
            video_path: Path to video file
            
        Returns:
            MultiModalResult with synchronization analysis
        """
        import time
        start_time = time.time()
        
        # Process audio
        audio_result = self._process_audio(audio_path)
        
        # Process video
        video_result = self._process_video(video_path)
        
        # Create media items
        audio_item = MediaItem(
            file_path=audio_path,
            media_type=MediaType.AUDIO,
            features=audio_result.get('features', {}),
            metadata=audio_result.get('metadata', {}),
        )
        
        video_item = MediaItem(
            file_path=video_path,
            media_type=MediaType.VIDEO,
            features=video_result.get('features', {}),
            metadata=video_result.get('metadata', {}),
        )
        
        # Check duration consistency
        audio_duration = audio_result.get('metadata', {}).get('duration_seconds', 0)
        video_duration = video_result.get('metadata', {}).get('duration_seconds', 0)
        
        duration_diff = abs(audio_duration - video_duration)
        
        # Perform cross-modal analysis
        cross_result = self._perform_cross_modal_analysis([audio_item, video_item])
        
        # Calculate consistency score
        consistency_score = cross_result.overall_score
        
        # Penalize for duration mismatch
        if audio_duration > 0 and video_duration > 0:
            duration_ratio = min(audio_duration, video_duration) / max(audio_duration, video_duration)
            if duration_ratio < 0.95:
                penalty = (1.0 - duration_ratio) * 30.0
                consistency_score = max(0, consistency_score - penalty)
        
        # Generate recommendations
        recommendations = [
            f"🎵 Audio duration: {audio_duration:.2f}s"
            f"🎬 Video duration: {video_duration:.2f}s"
        ]
        
        if duration_diff > 1.0:  # More than 1 second difference
            recommendations.append(
                f"⚠️ Duration mismatch: {duration_diff:.2f}s difference"
            )
        else:
            recommendations.append("✅ Duration match: Audio and video have similar durations")
        
        processing_time = time.time() - start_time
        
        return MultiModalResult(
            consistency_score=consistency_score,
            individual_results={
                MediaType.AUDIO: audio_result,
                MediaType.VIDEO: video_result,
            },
            cross_modal_analysis=cross_result,
            recommendations=recommendations,
            processing_time=processing_time,
        )
    
    def extract_text_from_image(self, image_path: str) -> str:
        """
        Extract text from an image using OCR.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Extracted text
        """
        if not HAS_TESSERACT or not HAS_PIL:
            raise ImportError("Tesseract and/or Pillow not available for OCR")
        
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)
            return text.strip()
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from image: {str(e)}")
    
    def check_semantic_consistency(self, text: str, image_features: Dict[str, Any]) -> float:
        """
        Check semantic consistency between text and image features.
        
        Args:
            text: Text content
            image_features: Features extracted from image
            
        Returns:
            Consistency score (0.0 to 1.0)
        """
        # Extract keywords from text
        if self.nlp:
            try:
                doc = self.nlp(text)
                text_keywords = [token.text.lower() for token in doc 
                               if token.pos_ in ('NOUN', 'VERB', 'ADJ')]
            except Exception:
                text_keywords = text.lower().split()
        else:
            text_keywords = text.lower().split()
        
        # Get image concepts
        image_concepts = []
        
        # From extracted text
        if 'extracted_text' in image_features:
            extracted_text = image_features['extracted_text']
            if self.nlp:
                try:
                    doc = self.nlp(extracted_text)
                    image_concepts.extend([token.text.lower() for token in doc 
                                         if token.pos_ in ('NOUN', 'VERB', 'ADJ')])
                except Exception:
                    image_concepts.extend(extracted_text.lower().split())
            else:
                image_concepts.extend(extracted_text.lower().split())
        
        # From color analysis
        if 'color_analysis' in image_features:
            color_analysis = image_features['color_analysis']
            if 'dominant_colors' in color_analysis:
                # Map colors to descriptive terms
                color_names = {
                    '#ff0000': 'red',
                    '#00ff00': 'green', 
                    '#0000ff': 'blue',
                    '#ffff00': 'yellow',
                    '#ff00ff': 'magenta',
                    '#00ffff': 'cyan',
                    '#ffffff': 'white',
                    '#000000': 'black',
                    '#808080': 'gray',
                }
                for color in color_analysis['dominant_colors']:
                    color_name = color_names.get(color, 'color')
                    image_concepts.append(color_name)
        
        # Calculate overlap
        if not text_keywords or not image_concepts:
            return 0.0
        
        text_set = set(text_keywords)
        image_set = set(image_concepts)
        
        intersection = len(text_set & image_set)
        union = len(text_set | image_set)
        
        if union == 0:
            return 0.0
        
        jaccard = intersection / union
        
        # Boost score if there are matching named entities
        if self.nlp:
            try:
                text_doc = self.nlp(text)
                text_entities = [ent.text.lower() for ent in text_doc.ents]
                
                if 'extracted_text' in image_features:
                    image_doc = self.nlp(image_features['extracted_text'])
                    image_entities = [ent.text.lower() for ent in image_doc.ents]
                    
                    entity_intersection = len(set(text_entities) & set(image_entities))
                    if entity_intersection > 0:
                        jaccard = min(1.0, jaccard + 0.2 * entity_intersection)
            except Exception:
                pass
        
        return jaccard
    
    # ==================== UTILITY METHODS ====================
    
    def get_available_methods(self) -> Dict[str, bool]:
        """Get availability of different analysis methods."""
        return {
            "Pillow": HAS_PIL,
            "OpenCV": HAS_OPENCV,
            "Tesseract OCR": HAS_TESSERACT,
            "pydub": HAS_PYDUB,
            "librosa": HAS_LIBROSA,
            "spaCy": HAS_SPACY,
        }
    
    def check_dependencies(self) -> List[str]:
        """Check which dependencies are missing."""
        missing = []
        
        if not HAS_PIL:
            missing.append("Pillow (for image processing)")
        if not HAS_OPENCV:
            missing.append("OpenCV (for video processing)")
        if not HAS_TESSERACT:
            missing.append("pytesseract (for OCR)")
        if not HAS_PYDUB:
            missing.append("pydub (for audio processing)")
        if not HAS_LIBROSA:
            missing.append("librosa (for advanced audio features)")
        if not HAS_SPACY:
            missing.append("spaCy (for NLP)")
        
        return missing
