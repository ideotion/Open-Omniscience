"""
Configuration for Email Intelligence Module

Handles configuration loading and management for email sources,
retrieval settings, and processing options.
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass, field
from .exceptions import EmailConfigError


@dataclass
class EmailSourceConfig:
    """Configuration for a single email source"""
    name: str
    source_type: str  # imap, pop3, api, rss
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    folders: List[str] = field(default_factory=list)
    fetch_since: Optional[str] = None
    interval_minutes: int = 60
    max_emails_per_fetch: int = 50
    
    def __post_init__(self):
        if not self.name:
            raise EmailConfigError("Email source name cannot be empty")
        if self.source_type not in ['imap', 'pop3', 'api', 'rss']:
            raise EmailConfigError(f"Invalid source type: {self.source_type}")


@dataclass
class ProcessingConfig:
    """Configuration for email processing"""
    store_raw_emails: bool = False
    extract_attachments: bool = True
    max_attachment_size_mb: int = 10
    supported_attachment_types: List[str] = field(default_factory=lambda: [
        'text/plain', 'text/html', 'application/pdf',
        'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'image/jpeg', 'image/png', 'image/gif'
    ])
    perform_ocr: bool = False
    ocr_languages: List[str] = field(default_factory=lambda: ['eng'])
    
    def __post_init__(self):
        self.max_attachment_size_bytes = self.max_attachment_size_mb * 1024 * 1024


@dataclass
class AnalysisConfig:
    """Configuration for email analysis"""
    extract_entities: bool = True
    perform_sentiment_analysis: bool = True
    detect_language: bool = True
    extract_keywords: bool = True
    analyze_network: bool = True
    
    # Entity extraction settings
    entity_types: List[str] = field(default_factory=lambda: [
        'PERSON', 'ORG', 'GPE', 'LOC', 'DATE', 'EMAIL', 'URL'
    ])


@dataclass
class EmailConfig:
    """Main configuration for Email Intelligence Module"""
    
    # Storage paths
    data_dir: Path = Path("data/emails")
    attachments_dir: Path = Path("data/attachments")
    raw_emails_dir: Path = Path("data/raw_emails")
    
    # Processing configuration
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    
    # Analysis configuration
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    
    # Email sources
    sources: List[EmailSourceConfig] = field(default_factory=list)
    
    # Scheduler settings
    scheduler_enabled: bool = True
    max_concurrent_fetches: int = 3
    retry_attempts: int = 3
    retry_delay_seconds: int = 300
    
    # Security settings
    encrypt_credentials: bool = True
    audit_logging: bool = True
    
    def __post_init__(self):
        # Create directories if they don't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        if self.processing.store_raw_emails:
            self.raw_emails_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate configuration
        self._validate()
    
    def _validate(self):
        """Validate the configuration"""
        if self.max_concurrent_fetches < 1:
            raise EmailConfigError("max_concurrent_fetches must be at least 1")
        if self.retry_attempts < 0:
            raise EmailConfigError("retry_attempts cannot be negative")
        if self.retry_delay_seconds < 0:
            raise EmailConfigError("retry_delay_seconds cannot be negative")
    
    @classmethod
    def from_yaml(cls, config_path: Optional[Path] = None) -> 'EmailConfig':
        """Load configuration from YAML file"""
        if config_path is None:
            # Try default paths
            default_paths = [
                Path("configs/email_sources.yaml"),
                Path("configs/email_config.yaml"),
                Path("email_config.yaml")
            ]
            
            for path in default_paths:
                if path.exists():
                    config_path = path
                    break
            else:
                # Return default configuration
                return cls()
        
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
        
        return cls(**config_data)
    
    def save_to_yaml(self, config_path: Path):
        """Save configuration to YAML file"""
        config_data = {
            'data_dir': str(self.data_dir),
            'attachments_dir': str(self.attachments_dir),
            'raw_emails_dir': str(self.raw_emails_dir),
            'processing': {
                'store_raw_emails': self.processing.store_raw_emails,
                'extract_attachments': self.processing.extract_attachments,
                'max_attachment_size_mb': self.processing.max_attachment_size_mb,
                'supported_attachment_types': self.processing.supported_attachment_types,
                'perform_ocr': self.processing.perform_ocr,
                'ocr_languages': self.processing.ocr_languages,
            },
            'analysis': {
                'extract_entities': self.analysis.extract_entities,
                'perform_sentiment_analysis': self.analysis.perform_sentiment_analysis,
                'detect_language': self.analysis.detect_language,
                'extract_keywords': self.analysis.extract_keywords,
                'analyze_network': self.analysis.analyze_network,
                'entity_types': self.analysis.entity_types,
            },
            'sources': [
                {
                    'name': source.name,
                    'source_type': source.source_type,
                    'enabled': source.enabled,
                    'config': source.config,
                    'folders': source.folders,
                    'fetch_since': source.fetch_since,
                    'interval_minutes': source.interval_minutes,
                    'max_emails_per_fetch': source.max_emails_per_fetch,
                }
                for source in self.sources
            ],
            'scheduler_enabled': self.scheduler_enabled,
            'max_concurrent_fetches': self.max_concurrent_fetches,
            'retry_attempts': self.retry_attempts,
            'retry_delay_seconds': self.retry_delay_seconds,
            'encrypt_credentials': self.encrypt_credentials,
            'audit_logging': self.audit_logging,
        }
        
        with open(config_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)


# Global configuration instance
config: Optional[EmailConfig] = None


def get_config() -> EmailConfig:
    """Get the global configuration instance"""
    global config
    if config is None:
        config = EmailConfig.from_yaml()
    return config


def reload_config() -> EmailConfig:
    """Reload the configuration from file"""
    global config
    config = EmailConfig.from_yaml()
    return config


def set_config(new_config: EmailConfig):
    """Set the global configuration instance"""
    global config
    config = new_config
