"""
Metadata Validator Module

Provides comprehensive metadata validation for images, audio, and video files.
Uses 100% FOSS libraries (Pillow, pydub, OpenCV) for offline metadata extraction
and validation.

This module can:
- Extract and validate EXIF data from images
- Extract and validate ID3 tags from audio files
- Extract and validate metadata from video files
- Check for inconsistencies and tampering indicators
- Verify timestamp and geolocation consistency
"""

import os
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

# Optional imports - will work without them but with reduced functionality
try:
    from PIL import Image, ExifTags, ImageOps
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

try:
    from pydub import AudioSegment
    from pydub.utils import which
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False
    AudioSegment = None

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


class MetadataType(Enum):
    """Types of metadata that can be validated."""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"
    UNKNOWN = "unknown"


class ValidationStatus(Enum):
    """Status of metadata validation."""
    VALID = "valid"
    SUSPICIOUS = "suspicious"
    INVALID = "invalid"
    TAMPERED = "tampered"
    MISSING = "missing"


@dataclass
class ValidationIssue:
    """Represents a single validation issue found in metadata."""
    issue_type: str
    severity: str  # "low", "medium", "high", "critical"
    description: str
    field: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    confidence: float = 1.0  # 0.0 to 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "confidence": self.confidence,
        }


@dataclass
class ValidationResult:
    """Result of metadata validation."""
    status: ValidationStatus
    metadata_type: MetadataType
    file_path: str
    file_hash: str  # SHA-256 hash of file
    file_size: int  # bytes
    file_type: str  # MIME type or extension
    timestamp: str  # ISO format timestamp
    issues: List[ValidationIssue] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0  # seconds
    model_version: str = "1.0.0"
    
    @property
    def is_valid(self) -> bool:
        """Check if validation passed."""
        return self.status == ValidationStatus.VALID
    
    @property
    def has_issues(self) -> bool:
        """Check if there are any issues."""
        return len(self.issues) > 0
    
    @property
    def critical_issues(self) -> List[ValidationIssue]:
        """Get critical severity issues."""
        return [i for i in self.issues if i.severity == "critical"]
    
    @property
    def high_issues(self) -> List[ValidationIssue]:
        """Get high severity issues."""
        return [i for i in self.issues if i.severity == "high"]
    
    @property
    def score(self) -> float:
        """Calculate a validation score (0-100)."""
        if not self.issues:
            return 100.0
        
        severity_weights = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
        total_weight = sum(severity_weights.get(issue.severity, 0.0) for issue in self.issues)
        max_possible = len(self.issues) * 1.0
        
        if max_possible == 0:
            return 100.0
        
        return max(0, 100.0 - (total_weight / max_possible) * 100.0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "metadata_type": self.metadata_type.value,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "timestamp": self.timestamp,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata,
            "processing_time": self.processing_time,
            "model_version": self.model_version,
            "score": self.score,
            "is_valid": self.is_valid,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class MetadataValidator:
    """
    Validates metadata from various media types (images, audio, video).
    
    This class provides comprehensive metadata extraction and validation
    capabilities using 100% FOSS libraries.
    
    Example usage:
        validator = MetadataValidator()
        result = validator.validate_image("path/to/image.jpg")
        print(f"Validation status: {result.status}")
        print(f"Score: {result.score:.1f}/100")
    """
    
    def __init__(self):
        """Initialize the metadata validator."""
        self._initialize_gps_tags()
    
    def _initialize_gps_tags(self) -> None:
        """Initialize GPS tag mappings."""
        # GPS tag information for EXIF
        self.gps_tags = {
            'GPSVersionID': 'GPS Version ID',
            'GPSLatitudeRef': 'GPS Latitude Reference',
            'GPSLatitude': 'GPS Latitude',
            'GPSLongitudeRef': 'GPS Longitude Reference',
            'GPSLongitude': 'GPS Longitude',
            'GPSAltitudeRef': 'GPS Altitude Reference',
            'GPSAltitude': 'GPS Altitude',
            'GPSTimeStamp': 'GPS Time Stamp',
            'GPSDateStamp': 'GPS Date Stamp',
        }
    
    def _calculate_file_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """Calculate SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        return os.path.getsize(file_path)
    
    def _get_file_extension(self, file_path: str) -> str:
        """Get file extension in lowercase."""
        return os.path.splitext(file_path)[1].lower()
    
    def _get_mime_type(self, file_path: str) -> str:
        """Get MIME type based on file extension."""
        ext = self._get_file_extension(file_path)
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.webp': 'image/webp',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska',
            '.wmv': 'video/x-ms-wmv',
        }
        return mime_types.get(ext, 'application/octet-stream')
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().isoformat() + 'Z'
    
    # ==================== IMAGE VALIDATION ====================
    
    def validate_image(self, file_path: str) -> ValidationResult:
        """
        Validate metadata of an image file.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            ValidationResult with validation status and details
        """
        import time
        start_time = time.time()
        
        file_path = str(file_path)
        
        # Check if file exists
        if not os.path.exists(file_path):
            return ValidationResult(
                status=ValidationStatus.INVALID,
                metadata_type=MetadataType.IMAGE,
                file_path=file_path,
                file_hash="",
                file_size=0,
                file_type="unknown",
                timestamp=self._get_timestamp(),
                issues=[ValidationIssue(
                    issue_type="file_not_found",
                    severity="critical",
                    description=f"File not found: {file_path}",
                    field="file_path",
                )],
                processing_time=time.time() - start_time,
            )
        
        # Calculate file hash and size
        file_hash = self._calculate_file_hash(file_path)
        file_size = self._get_file_size(file_path)
        file_type = self._get_mime_type(file_path)
        
        issues: List[ValidationIssue] = []
        metadata: Dict[str, Any] = {}
        
        # Try to extract EXIF data
        if HAS_PIL:
            try:
                with Image.open(file_path) as img:
                    metadata = self._extract_exif_data(img)
                    metadata['image_info'] = self._extract_image_info(img)
                    
                # Validate EXIF data
                exif_issues = self._validate_exif_data(metadata)
                issues.extend(exif_issues)
                
            except Exception as e:
                issues.append(ValidationIssue(
                    issue_type="image_open_error",
                    severity="high",
                    description=f"Failed to open image: {str(e)}",
                    field="image_open",
                ))
        else:
            issues.append(ValidationIssue(
                issue_type="missing_dependency",
                severity="medium",
                description="Pillow library not available for EXIF extraction",
                field="dependency",
            ))
        
        # Determine status
        if any(issue.severity == "critical" for issue in issues):
            status = ValidationStatus.INVALID
        elif any(issue.severity == "high" for issue in issues):
            status = ValidationStatus.TAMPERED
        elif issues:
            status = ValidationStatus.SUSPICIOUS
        else:
            status = ValidationStatus.VALID
        
        processing_time = time.time() - start_time
        
        return ValidationResult(
            status=status,
            metadata_type=MetadataType.IMAGE,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_type=file_type,
            timestamp=self._get_timestamp(),
            issues=issues,
            metadata=metadata,
            processing_time=processing_time,
        )
    
    def _extract_exif_data(self, img) -> Dict[str, Any]:
        """Extract EXIF data from PIL Image."""
        exif_data = {}
        
        try:
            # Get basic EXIF data
            if hasattr(img, '_getexif'):
                exif_info = img._getexif()
                if exif_info:
                    for tag_id, value in exif_info.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        exif_data[tag_name] = value
        except Exception:
            pass
        
        return exif_data
    
    def _extract_image_info(self, img) -> Dict[str, Any]:
        """Extract basic image information."""
        info = {
            'format': img.format,
            'mode': img.mode,
            'size': {'width': img.width, 'height': img.height},
            'aspect_ratio': img.width / img.height if img.height > 0 else 0,
        }
        
        # Check if image has transparency
        if img.mode in ('RGBA', 'LA', 'PA'):
            info['has_transparency'] = True
        else:
            info['has_transparency'] = False
        
        # Check color space
        if img.mode == 'RGB':
            info['color_space'] = 'RGB'
        elif img.mode == 'L':
            info['color_space'] = 'Grayscale'
        elif img.mode == 'CMYK':
            info['color_space'] = 'CMYK'
        else:
            info['color_space'] = img.mode
        
        return info
    
    def _validate_exif_data(self, metadata: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate EXIF data for inconsistencies and tampering indicators."""
        issues = []
        
        # Check for common tampering indicators
        exif_data = metadata.get('EXIF', {})
        
        # 1. Check if EXIF data exists at all
        if not exif_data and not metadata.get('image_info'):
            issues.append(ValidationIssue(
                issue_type="missing_exif",
                severity="medium",
                description="No EXIF data found in image",
                field="EXIF",
            ))
        
        # 2. Check for stripped EXIF (common in manipulated images)
        if metadata.get('image_info'):
            img_info = metadata['image_info']
            if img_info.get('format') in ['JPEG', 'PNG'] and not exif_data:
                issues.append(ValidationIssue(
                    issue_type="stripped_exif",
                    severity="medium",
                    description="EXIF data appears to be stripped",
                    field="EXIF",
                    confidence=0.8,
                ))
        
        # 3. Check for inconsistent timestamps
        timestamps = []
        for key, value in exif_data.items():
            if 'Date' in key or 'Time' in key:
                timestamps.append((key, value))
        
        if len(timestamps) > 1:
            # Check if timestamps are consistent
            for i in range(len(timestamps) - 1):
                for j in range(i + 1, len(timestamps)):
                    ts1, ts2 = timestamps[i][1], timestamps[j][1]
                    if ts1 != ts2:
                        issues.append(ValidationIssue(
                            issue_type="timestamp_inconsistency",
                            severity="high",
                            description=f"Inconsistent timestamps: {timestamps[i][0]} vs {timestamps[j][0]}",
                            field="timestamp",
                            expected=str(ts1),
                            actual=str(ts2),
                        ))
        
        # 4. Check GPS data consistency
        gps_data = {k: v for k, v in exif_data.items() if 'GPS' in k}
        if gps_data:
            gps_issues = self._validate_gps_data(gps_data)
            issues.extend(gps_issues)
        
        # 5. Check for unusual camera settings
        if 'ExposureTime' in exif_data:
            exposure = exif_data['ExposureTime']
            # Very long or very short exposures can be suspicious
            if exposure and (exposure > 1/30 or exposure < 1/1000):
                issues.append(ValidationIssue(
                    issue_type="unusual_exposure",
                    severity="low",
                    description=f"Unusual exposure time: {exposure}s",
                    field="ExposureTime",
                    confidence=0.6,
                ))
        
        # 6. Check for unusual ISO values
        if 'PhotographicSensitivity' in exif_data:
            iso = exif_data['PhotographicSensitivity']
            if iso and iso > 6400:
                issues.append(ValidationIssue(
                    issue_type="high_iso",
                    severity="low",
                    description=f"High ISO value: {iso}",
                    field="PhotographicSensitivity",
                    confidence=0.5,
                ))
        
        # 7. Check for software that might indicate editing
        if 'Software' in exif_data:
            software = str(exif_data['Software']).lower()
            editing_software = ['photoshop', 'gimp', 'lightroom', 'paint', 'editor']
            if any(sw in software for sw in editing_software):
                issues.append(ValidationIssue(
                    issue_type="editing_software_detected",
                    severity="medium",
                    description=f"Editing software detected: {exif_data['Software']}",
                    field="Software",
                    confidence=0.9,
                ))
        
        return issues
    
    def _validate_gps_data(self, gps_data: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate GPS data for consistency."""
        issues = []
        
        # Check if we have both latitude and longitude
        has_lat = any('Latitude' in k for k in gps_data.keys())
        has_lon = any('Longitude' in k for k in gps_data.keys())
        
        if has_lat != has_lon:
            issues.append(ValidationIssue(
                issue_type="incomplete_gps",
                severity="medium",
                description="GPS data is incomplete (missing latitude or longitude)",
                field="GPS",
            ))
        
        # Check if GPS coordinates are valid
        if has_lat:
            lat_valid = self._validate_gps_coordinate(
                gps_data.get('GPSLatitude'), 
                gps_data.get('GPSLatitudeRef')
            )
            if not lat_valid:
                issues.append(ValidationIssue(
                    issue_type="invalid_gps_latitude",
                    severity="high",
                    description="Invalid GPS latitude coordinates",
                    field="GPSLatitude",
                ))
        
        if has_lon:
            lon_valid = self._validate_gps_coordinate(
                gps_data.get('GPSLongitude'),
                gps_data.get('GPSLongitudeRef')
            )
            if not lon_valid:
                issues.append(ValidationIssue(
                    issue_type="invalid_gps_longitude",
                    severity="high",
                    description="Invalid GPS longitude coordinates",
                    field="GPSLongitude",
                ))
        
        return issues
    
    def _validate_gps_coordinate(self, coord: Any, ref: Any) -> bool:
        """Validate GPS coordinate format."""
        if coord is None or ref is None:
            return False
        
        try:
            # GPS coordinates are typically stored as rational numbers
            # Format: ((degrees_num, degrees_denom), (minutes_num, minutes_denom), (seconds_num, seconds_denom))
            if isinstance(coord, tuple) and len(coord) == 3:
                deg, min, sec = coord
                
                # Convert to decimal
                def convert_rational(r):
                    if isinstance(r, tuple) and len(r) == 2:
                        return r[0] / r[1]
                    return float(r)
                
                deg_val = convert_rational(deg)
                min_val = convert_rational(min)
                sec_val = convert_rational(sec)
                
                decimal = deg_val + (min_val / 60) + (sec_val / 3600)
                
                # Check if coordinate is within valid range
                if ref in ['N', 'E']:
                    return 0 <= decimal <= 90
                elif ref in ['S', 'W']:
                    return -90 <= decimal <= 0
                else:
                    return False
            
            return False
            
        except (ValueError, TypeError, ZeroDivisionError):
            return False
    
    # ==================== AUDIO VALIDATION ====================
    
    def validate_audio(self, file_path: str) -> ValidationResult:
        """
        Validate metadata of an audio file.
        
        Args:
            file_path: Path to the audio file
            
        Returns:
            ValidationResult with validation status and details
        """
        import time
        start_time = time.time()
        
        file_path = str(file_path)
        
        # Check if file exists
        if not os.path.exists(file_path):
            return ValidationResult(
                status=ValidationStatus.INVALID,
                metadata_type=MetadataType.AUDIO,
                file_path=file_path,
                file_hash="",
                file_size=0,
                file_type="unknown",
                timestamp=self._get_timestamp(),
                issues=[ValidationIssue(
                    issue_type="file_not_found",
                    severity="critical",
                    description=f"File not found: {file_path}",
                    field="file_path",
                )],
                processing_time=time.time() - start_time,
            )
        
        # Calculate file hash and size
        file_hash = self._calculate_file_hash(file_path)
        file_size = self._get_file_size(file_path)
        file_type = self._get_mime_type(file_path)
        
        issues: List[ValidationIssue] = []
        metadata: Dict[str, Any] = {}
        
        # Try to extract audio metadata
        if HAS_PYDUB:
            try:
                audio = AudioSegment.from_file(file_path)
                metadata = self._extract_audio_metadata(audio, file_path)
                
                # Validate audio metadata
                audio_issues = self._validate_audio_metadata(metadata)
                issues.extend(audio_issues)
                
            except Exception as e:
                issues.append(ValidationIssue(
                    issue_type="audio_open_error",
                    severity="high",
                    description=f"Failed to open audio file: {str(e)}",
                    field="audio_open",
                ))
        else:
            issues.append(ValidationIssue(
                issue_type="missing_dependency",
                severity="medium",
                description="pydub library not available for audio metadata extraction",
                field="dependency",
            ))
        
        # Try to extract ID3 tags if available
        if HAS_PYDUB:
            try:
                from pydub.utils import mediainfo
                info = mediainfo(file_path)
                if info:
                    metadata['id3_tags'] = self._extract_id3_tags(info)
            except Exception:
                pass
        
        # Determine status
        if any(issue.severity == "critical" for issue in issues):
            status = ValidationStatus.INVALID
        elif any(issue.severity == "high" for issue in issues):
            status = ValidationStatus.TAMPERED
        elif issues:
            status = ValidationStatus.SUSPICIOUS
        else:
            status = ValidationStatus.VALID
        
        processing_time = time.time() - start_time
        
        return ValidationResult(
            status=status,
            metadata_type=MetadataType.AUDIO,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_type=file_type,
            timestamp=self._get_timestamp(),
            issues=issues,
            metadata=metadata,
            processing_time=processing_time,
        )
    
    def _extract_audio_metadata(self, audio: Any, file_path: str) -> Dict[str, Any]:
        """Extract metadata from audio file."""
        metadata = {
            'duration_seconds': len(audio) / 1000.0,  # pydub uses milliseconds
            'sample_width': audio.sample_width,
            'frame_rate': audio.frame_rate,
            'channels': audio.channels,
            'frame_width': audio.frame_width,
        }
        
        # Add file-specific info
        ext = self._get_file_extension(file_path)
        metadata['format'] = ext.lstrip('.')
        
        return metadata
    
    def _extract_id3_tags(self, media_info: Dict[str, Any]) -> Dict[str, Any]:
        """Extract ID3 tags from media info."""
        tags = {}
        
        # Common ID3 tag fields
        id3_fields = [
            'title', 'artist', 'album', 'album_artist', 'genre',
            'track_number', 'track_total', 'disc_number', 'disc_total',
            'date', 'year', 'comment', 'composer', 'lyricist',
            'copyright', 'url', 'encoded_by', 'publisher'
        ]
        
        for field in id3_fields:
            if field in media_info:
                tags[field] = media_info[field]
        
        return tags
    
    def _validate_audio_metadata(self, metadata: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate audio metadata for inconsistencies."""
        issues = []
        
        # Check for unusually long duration
        duration = metadata.get('duration_seconds', 0)
        if duration > 3600:  # More than 1 hour
            issues.append(ValidationIssue(
                issue_type="long_duration",
                severity="low",
                description=f"Unusually long audio duration: {duration:.1f} seconds",
                field="duration_seconds",
                confidence=0.5,
            ))
        
        # Check for unusually short duration
        if 0 < duration < 1:
            issues.append(ValidationIssue(
                issue_type="short_duration",
                severity="low",
                description=f"Unusually short audio duration: {duration:.3f} seconds",
                field="duration_seconds",
                confidence=0.6,
            ))
        
        # Check sample rate
        sample_rate = metadata.get('frame_rate', 0)
        if sample_rate < 8000 or sample_rate > 192000:
            issues.append(ValidationIssue(
                issue_type="unusual_sample_rate",
                severity="medium",
                description=f"Unusual sample rate: {sample_rate} Hz",
                field="frame_rate",
                confidence=0.7,
            ))
        
        # Check channels
        channels = metadata.get('channels', 0)
        if channels < 1 or channels > 8:
            issues.append(ValidationIssue(
                issue_type="unusual_channels",
                severity="medium",
                description=f"Unusual number of channels: {channels}",
                field="channels",
                confidence=0.7,
            ))
        
        # Validate ID3 tags
        id3_tags = metadata.get('id3_tags', {})
        if id3_tags:
            id3_issues = self._validate_id3_tags(id3_tags)
            issues.extend(id3_issues)
        
        return issues
    
    def _validate_id3_tags(self, tags: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate ID3 tags for inconsistencies."""
        issues = []
        
        # Check for empty required fields
        if 'title' not in tags or not tags.get('title'):
            issues.append(ValidationIssue(
                issue_type="missing_title",
                severity="low",
                description="Missing or empty title tag",
                field="title",
                confidence=0.5,
            ))
        
        # Check year format
        if 'year' in tags:
            year = tags['year']
            try:
                year_int = int(year)
                if year_int < 1900 or year_int > datetime.utcnow().year + 1:
                    issues.append(ValidationIssue(
                        issue_type="invalid_year",
                        severity="medium",
                        description=f"Invalid year: {year}",
                        field="year",
                        confidence=0.8,
                    ))
            except ValueError:
                issues.append(ValidationIssue(
                    issue_type="invalid_year_format",
                    severity="medium",
                    description=f"Invalid year format: {year}",
                    field="year",
                    confidence=0.9,
                ))
        
        # Check for suspicious software tags
        if 'encoded_by' in tags:
            software = str(tags['encoded_by']).lower()
            suspicious_software = ['audacity', 'adobe', 'sonar', 'fl studio', 'ableton']
            if any(sw in software for sw in suspicious_software):
                issues.append(ValidationIssue(
                    issue_type="audio_editing_software",
                    severity="medium",
                    description=f"Audio editing software detected: {tags['encoded_by']}",
                    field="encoded_by",
                    confidence=0.8,
                ))
        
        return issues
    
    # ==================== VIDEO VALIDATION ====================
    
    def validate_video(self, file_path: str) -> ValidationResult:
        """
        Validate metadata of a video file.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            ValidationResult with validation status and details
        """
        import time
        start_time = time.time()
        
        file_path = str(file_path)
        
        # Check if file exists
        if not os.path.exists(file_path):
            return ValidationResult(
                status=ValidationStatus.INVALID,
                metadata_type=MetadataType.VIDEO,
                file_path=file_path,
                file_hash="",
                file_size=0,
                file_type="unknown",
                timestamp=self._get_timestamp(),
                issues=[ValidationIssue(
                    issue_type="file_not_found",
                    severity="critical",
                    description=f"File not found: {file_path}",
                    field="file_path",
                )],
                processing_time=time.time() - start_time,
            )
        
        # Calculate file hash and size
        file_hash = self._calculate_file_hash(file_path)
        file_size = self._get_file_size(file_path)
        file_type = self._get_mime_type(file_path)
        
        issues: List[ValidationIssue] = []
        metadata: Dict[str, Any] = {}
        
        # Try to extract video metadata with OpenCV
        if HAS_OPENCV:
            try:
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    metadata = self._extract_video_metadata(cap)
                    cap.release()
                    
                    # Validate video metadata
                    video_issues = self._validate_video_metadata(metadata)
                    issues.extend(video_issues)
                else:
                    issues.append(ValidationIssue(
                        issue_type="video_open_error",
                        severity="high",
                        description="Failed to open video file with OpenCV",
                        field="video_open",
                    ))
            except Exception as e:
                issues.append(ValidationIssue(
                    issue_type="video_processing_error",
                    severity="high",
                    description=f"Error processing video: {str(e)}",
                    field="video_processing",
                ))
        else:
            issues.append(ValidationIssue(
                issue_type="missing_dependency",
                severity="medium",
                description="OpenCV library not available for video metadata extraction",
                field="dependency",
            ))
        
        # Try to extract additional metadata with ffmpeg
        if HAS_PYDUB:
            try:
                from pydub.utils import mediainfo
                info = mediainfo(file_path)
                if info:
                    metadata['ffmpeg_info'] = info
            except Exception:
                pass
        
        # Determine status
        if any(issue.severity == "critical" for issue in issues):
            status = ValidationStatus.INVALID
        elif any(issue.severity == "high" for issue in issues):
            status = ValidationStatus.TAMPERED
        elif issues:
            status = ValidationStatus.SUSPICIOUS
        else:
            status = ValidationStatus.VALID
        
        processing_time = time.time() - start_time
        
        return ValidationResult(
            status=status,
            metadata_type=MetadataType.VIDEO,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            file_type=file_type,
            timestamp=self._get_timestamp(),
            issues=issues,
            metadata=metadata,
            processing_time=processing_time,
        )
    
    def _extract_video_metadata(self, cap) -> Dict[str, Any]:
        """Extract metadata from video file using OpenCV."""
        metadata = {}
        
        # Get video properties
        metadata['frame_count'] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        metadata['fps'] = cap.get(cv2.CAP_PROP_FPS)
        metadata['duration_seconds'] = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        metadata['frame_width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        metadata['frame_height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        metadata['fourcc'] = cap.get(cv2.CAP_PROP_FOURCC)
        
        # Calculate aspect ratio
        width = metadata['frame_width']
        height = metadata['frame_height']
        if height > 0:
            metadata['aspect_ratio'] = width / height
        else:
            metadata['aspect_ratio'] = 0
        
        # Get codec information
        fourcc = metadata['fourcc']
        if isinstance(fourcc, float):
            fourcc_int = int(fourcc)
            metadata['codec'] = chr(fourcc_int & 0xFF) + \
                               chr((fourcc_int >> 8) & 0xFF) + \
                               chr((fourcc_int >> 16) & 0xFF) + \
                               chr((fourcc_int >> 24) & 0xFF)
        else:
            metadata['codec'] = str(fourcc)
        
        return metadata
    
    def _validate_video_metadata(self, metadata: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate video metadata for inconsistencies."""
        issues = []
        
        # Check for zero or negative values
        if metadata.get('frame_count', 0) <= 0:
            issues.append(ValidationIssue(
                issue_type="invalid_frame_count",
                severity="high",
                description=f"Invalid frame count: {metadata.get('frame_count')}",
                field="frame_count",
            ))
        
        if metadata.get('fps', 0) <= 0:
            issues.append(ValidationIssue(
                issue_type="invalid_fps",
                severity="high",
                description=f"Invalid FPS: {metadata.get('fps')}",
                field="fps",
            ))
        
        if metadata.get('duration_seconds', 0) <= 0:
            issues.append(ValidationIssue(
                issue_type="invalid_duration",
                severity="high",
                description=f"Invalid duration: {metadata.get('duration_seconds')}s",
                field="duration_seconds",
            ))
        
        # Check for unusually high FPS
        fps = metadata.get('fps', 0)
        if fps > 120:
            issues.append(ValidationIssue(
                issue_type="high_fps",
                severity="medium",
                description=f"Unusually high FPS: {fps}",
                field="fps",
                confidence=0.7,
            ))
        
        # Check for unusually low FPS
        if 0 < fps < 10:
            issues.append(ValidationIssue(
                issue_type="low_fps",
                severity="medium",
                description=f"Unusually low FPS: {fps}",
                field="fps",
                confidence=0.7,
            ))
        
        # Check for unusual resolution
        width = metadata.get('frame_width', 0)
        height = metadata.get('frame_height', 0)
        
        if width < 16 or height < 16:
            issues.append(ValidationIssue(
                issue_type="tiny_resolution",
                severity="high",
                description=f"Extremely small resolution: {width}x{height}",
                field="resolution",
            ))
        
        if width > 8192 or height > 8192:
            issues.append(ValidationIssue(
                issue_type="huge_resolution",
                severity="medium",
                description=f"Extremely large resolution: {width}x{height}",
                field="resolution",
                confidence=0.6,
            ))
        
        # Check aspect ratio for common values
        aspect_ratio = metadata.get('aspect_ratio', 0)
        common_aspect_ratios = [16/9, 4/3, 1.0, 21/9, 32/9]
        if aspect_ratio > 0:
            is_common = any(abs(aspect_ratio - common) < 0.01 for common in common_aspect_ratios)
            if not is_common:
                issues.append(ValidationIssue(
                    issue_type="unusual_aspect_ratio",
                    severity="low",
                    description=f"Unusual aspect ratio: {aspect_ratio:.3f}",
                    field="aspect_ratio",
                    confidence=0.5,
                ))
        
        # Check for unusual duration
        duration = metadata.get('duration_seconds', 0)
        if duration > 3600:  # More than 1 hour
            issues.append(ValidationIssue(
                issue_type="long_duration",
                severity="low",
                description=f"Unusually long video duration: {duration:.1f} seconds",
                field="duration_seconds",
                confidence=0.5,
            ))
        
        if 0 < duration < 1:
            issues.append(ValidationIssue(
                issue_type="short_duration",
                severity="low",
                description=f"Unusually short video duration: {duration:.3f} seconds",
                field="duration_seconds",
                confidence=0.6,
            ))
        
        return issues
    
    # ==================== CROSS-MEDIA VALIDATION ====================
    
    def validate_consistency(self, media_items: List[str]) -> ValidationResult:
        """
        Validate consistency across multiple media items.
        
        Args:
            media_items: List of file paths to validate together
            
        Returns:
            ValidationResult with cross-media consistency analysis
        """
        import time
        start_time = time.time()
        
        if not media_items:
            return ValidationResult(
                status=ValidationStatus.INVALID,
                metadata_type=MetadataType.UNKNOWN,
                file_path="",
                file_hash="",
                file_size=0,
                file_type="unknown",
                timestamp=self._get_timestamp(),
                issues=[ValidationIssue(
                    issue_type="no_media_items",
                    severity="critical",
                    description="No media items provided for consistency validation",
                    field="media_items",
                )],
                processing_time=time.time() - start_time,
            )
        
        # Validate each media item individually
        individual_results = []
        all_metadata = []
        all_issues = []
        
        for media_path in media_items:
            # Determine media type based on extension
            ext = self._get_file_extension(media_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
                result = self.validate_image(media_path)
            elif ext in ['.mp3', '.wav', '.ogg', '.flac', '.aac']:
                result = self.validate_audio(media_path)
            elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']:
                result = self.validate_video(media_path)
            else:
                result = ValidationResult(
                    status=ValidationStatus.INVALID,
                    metadata_type=MetadataType.UNKNOWN,
                    file_path=media_path,
                    file_hash="",
                    file_size=0,
                    file_type="unknown",
                    timestamp=self._get_timestamp(),
                    issues=[ValidationIssue(
                        issue_type="unsupported_format",
                        severity="high",
                        description=f"Unsupported media format: {ext}",
                        field="format",
                    )],
                    processing_time=0,
                )
            
            individual_results.append(result)
            all_metadata.append(result.metadata)
            all_issues.extend(result.issues)
        
        # Perform cross-media validation
        cross_issues = self._validate_cross_media(all_metadata, media_items)
        all_issues.extend(cross_issues)
        
        # Determine overall status
        if any(issue.severity == "critical" for issue in all_issues):
            status = ValidationStatus.INVALID
        elif any(issue.severity == "high" for issue in all_issues):
            status = ValidationStatus.TAMPERED
        elif all_issues:
            status = ValidationStatus.SUSPICIOUS
        else:
            status = ValidationStatus.VALID
        
        processing_time = time.time() - start_time
        
        # Combine all metadata
        combined_metadata = {
            'individual_results': [r.to_dict() for r in individual_results],
            'cross_media_analysis': self._perform_cross_media_analysis(all_metadata, media_items)
        }
        
        return ValidationResult(
            status=status,
            metadata_type=MetadataType.UNKNOWN,
            file_path=", ".join(media_items),
            file_hash="",
            file_size=sum(r.file_size for r in individual_results),
            file_type="multiple",
            timestamp=self._get_timestamp(),
            issues=all_issues,
            metadata=combined_metadata,
            processing_time=processing_time,
        )
    
    def _validate_cross_media(self, metadata_list: List[Dict[str, Any]], file_paths: List[str]) -> List[ValidationIssue]:
        """Validate consistency across multiple media items."""
        issues = []
        
        # Check if we have multiple media items
        if len(metadata_list) < 2:
            return issues
        
        # Extract timestamps from all media
        timestamps = []
        for i, metadata in enumerate(metadata_list):
            # Look for creation/modification timestamps
            for key, value in metadata.items():
                if 'date' in key.lower() or 'time' in key.lower():
                    timestamps.append((file_paths[i], key, value))
        
        # Check for timestamp inconsistencies across media
        if len(timestamps) > 1:
            # Group by media file
            media_timestamps = {}
            for file_path, field, value in timestamps:
                if file_path not in media_timestamps:
                    media_timestamps[file_path] = []
                media_timestamps[file_path].append((field, value))
            
            # Compare timestamps across different files
            for i, (file1, ts_list1) in enumerate(media_timestamps.items()):
                for file2, ts_list2 in list(media_timestamps.items())[i+1:]:
                    # Compare each timestamp pair
                    for field1, value1 in ts_list1:
                        for field2, value2 in ts_list2:
                            if value1 != value2:
                                issues.append(ValidationIssue(
                                    issue_type="cross_media_timestamp_inconsistency",
                                    severity="high",
                                    description=f"Timestamp inconsistency between {file1} and {file2}",
                                    field=f"{field1} vs {field2}",
                                    expected=str(value1),
                                    actual=str(value2),
                                ))
        
        # Check for GPS location consistency
        gps_locations = []
        for i, metadata in enumerate(metadata_list):
            gps_data = {k: v for k, v in metadata.items() if 'GPS' in k or 'gps' in k}
            if gps_data:
                gps_locations.append((file_paths[i], gps_data))
        
        if len(gps_locations) > 1:
            # Compare GPS locations
            for i, (file1, gps1) in enumerate(gps_locations):
                for file2, gps2 in gps_locations[i+1:]:
                    if gps1 != gps2:
                        issues.append(ValidationIssue(
                            issue_type="cross_media_location_inconsistency",
                            severity="high",
                            description=f"Location inconsistency between {file1} and {file2}",
                            field="GPS",
                        ))
        
        return issues
    
    def _perform_cross_media_analysis(self, metadata_list: List[Dict[str, Any]], file_paths: List[str]) -> Dict[str, Any]:
        """Perform detailed cross-media analysis."""
        analysis = {
            'timestamp_consistency': self._analyze_timestamp_consistency(metadata_list),
            'location_consistency': self._analyze_location_consistency(metadata_list),
            'format_consistency': self._analyze_format_consistency(file_paths),
        }
        return analysis
    
    def _analyze_timestamp_consistency(self, metadata_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze timestamp consistency across media."""
        timestamps = []
        for metadata in metadata_list:
            for key, value in metadata.items():
                if 'date' in key.lower() or 'time' in key.lower():
                    timestamps.append(value)
        
        if not timestamps:
            return {"status": "no_timestamps", "count": 0}
        
        # Count unique timestamps
        unique_timestamps = set(str(ts) for ts in timestamps)
        
        if len(unique_timestamps) == 1:
            return {"status": "consistent", "count": len(timestamps), "unique": 1}
        elif len(unique_timestamps) == len(timestamps):
            return {"status": "inconsistent", "count": len(timestamps), "unique": len(unique_timestamps)}
        else:
            return {"status": "partially_consistent", "count": len(timestamps), "unique": len(unique_timestamps)}
    
    def _analyze_location_consistency(self, metadata_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze location consistency across media."""
        locations = []
        for metadata in metadata_list:
            gps_data = {k: v for k, v in metadata.items() if 'GPS' in k or 'gps' in k}
            if gps_data:
                locations.append(gps_data)
        
        if not locations:
            return {"status": "no_locations", "count": 0}
        
        # Count unique locations
        unique_locations = len(set(str(loc) for loc in locations))
        
        if unique_locations == 1:
            return {"status": "consistent", "count": len(locations), "unique": 1}
        elif unique_locations == len(locations):
            return {"status": "inconsistent", "count": len(locations), "unique": unique_locations}
        else:
            return {"status": "partially_consistent", "count": len(locations), "unique": unique_locations}
    
    def _analyze_format_consistency(self, file_paths: List[str]) -> Dict[str, Any]:
        """Analyze format consistency across media."""
        formats = [self._get_file_extension(fp) for fp in file_paths]
        unique_formats = set(formats)
        
        if len(unique_formats) == 1:
            return {"status": "consistent", "formats": list(unique_formats)}
        else:
            return {"status": "mixed", "formats": list(unique_formats), "count": len(unique_formats)}
    
    # ==================== UTILITY METHODS ====================
    
    def get_supported_formats(self) -> Dict[MetadataType, List[str]]:
        """Get list of supported formats for each media type."""
        return {
            MetadataType.IMAGE: ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'],
            MetadataType.AUDIO: ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'],
            MetadataType.VIDEO: ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'],
        }
    
    def check_dependencies(self) -> Dict[str, bool]:
        """Check which optional dependencies are available."""
        return {
            "Pillow": HAS_PIL,
            "pydub": HAS_PYDUB,
            "OpenCV": HAS_OPENCV,
            "Tesseract": HAS_TESSERACT,
        }
