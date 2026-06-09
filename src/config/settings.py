"""
Open Omniscience - Configuration Settings

Centralized configuration management for the Open Omniscience platform.
This module provides a unified way to access configuration settings from
environment variables and YAML files.

Author: Ideotion
License: GNU GPLv3
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


def _package_version() -> str:
    """Single source of truth for the app version (finding BUG-03).

    Reads the installed package metadata (the same value /api/health reports and
    pyproject declares) so the version can never drift from the literals that
    previously lived here ("0.02") and in configs/settings.yaml ("0.03").
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("open-omniscience")
        except PackageNotFoundError:
            return "0.0.0"
    except Exception:
        return "0.0.0"

import yaml

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class Config:
    """
    Main configuration class that holds all configuration settings.
    
    Configuration is loaded from multiple sources in the following order (later overrides earlier):
    1. Default values (defined in dataclass fields)
    2. YAML configuration files
    3. Environment variables
    """
    # Database configuration
    database_url: str = "sqlite:///data/open_omniscience.db"
    database_echo: bool = False
    
    # Scraping configuration
    max_workers: int = 5
    max_retries: int = 3
    initial_retry_delay: float = 1.0
    timeout: int = 10
    user_agent: str = "OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"
    rate_limit_ms: int = 2000
    
    # Rate limiting configuration
    global_rate_limit: str = "100/hour"
    search_rate_limit: str = "100/hour"
    export_rate_limit: str = "50/hour"
    sources_rate_limit: str = "100/hour"
    llm_rate_limit: str = "10/minute"
    
    # Security configuration
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    cors_allow_credentials: bool = True
    cors_allow_methods: str = "GET,POST,PUT,DELETE,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,Accept,Origin,User-Agent"
    # (finding SEC-02) secret_key / csrf_secret / jwt_* removed: no code consumed
    # them. CSRF is enforced by a loopback Origin/Referer check in the API
    # middleware (src/api/main.py), not by a secret, and there is no auth system.
    
    # Logging configuration
    log_level: str = "INFO"
    log_file: str = "logs/open_omniscience.log"
    max_log_size: int = 10485760  # 10MB
    backup_count: int = 5
    audit_enabled: bool = True
    audit_log_dir: str = "audit"
    
    # LLM configuration.
    # Secure-by-default (finding SEC-05): bind Ollama to loopback and scope its
    # CORS to loopback rather than the old 0.0.0.0 / "*" which would expose the
    # local LLM daemon to the network. These fields are currently informational
    # (the running app reaches Ollama via OO_OLLAMA_URL); kept honest regardless.
    ollama_host: str = "127.0.0.1"
    ollama_origins: str = "http://127.0.0.1:11434"
    ollama_base_url: str = "http://127.0.0.1:11434"
    # No code path auto-downloads models (the API returns "run: ollama pull ..."
    # when a model is missing); default False so the field cannot misrepresent it.
    auto_download_models: bool = False
    download_default_models: bool = False
    llm_timeout: int = 120
    llm_max_tokens: int = 4096
    llm_max_context_length: int = 8192
    
    # Application configuration
    app_name: str = "Open Omniscience"
    app_version: str = field(default_factory=_package_version)
    app_debug: bool = False
    app_environment: str = "development"
    articles_per_page: int = 20
    default_language: str = "en"
    theme: str = "system"

    # Chain of custody: when true, every successful ingest appends a signed,
    # hash-chained custody entry (src/custody). Off by default -- it is an
    # explicit, opt-in evidentiary feature, not silent always-on behaviour, and it
    # has a (small) per-article signing cost. Toggle with OO_CUSTODY_ON_INGEST=1.
    custody_on_ingest: bool = False

    # Path to the repository root
    repo_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.resolve())
    
    # Additional configuration that doesn't fit in the above categories
    extra: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize configuration from various sources."""
        self._load_env()
        self._load_yaml_files()
        self._validate()
    
    def _load_env(self):
        """Load configuration from environment variables."""
        # Database
        if db_url := os.getenv("DATABASE_URL"):
            self.database_url = db_url
        if db_echo := os.getenv("DATABASE_ECHO"):
            self.database_echo = db_echo.lower() == "true"
        
        # Scraping
        if max_workers := os.getenv("MAX_WORKERS"):
            self.max_workers = int(max_workers)
        if max_retries := os.getenv("MAX_RETRIES"):
            self.max_retries = int(max_retries)
        if timeout := os.getenv("REQUEST_TIMEOUT"):
            self.timeout = int(timeout)
        if user_agent := os.getenv("USER_AGENT"):
            self.user_agent = user_agent
        if rate_limit_ms := os.getenv("RATE_LIMIT_MS"):
            self.rate_limit_ms = int(rate_limit_ms)
        
        # Rate Limiting
        if global_limit := os.getenv("GLOBAL_RATE_LIMIT"):
            self.global_rate_limit = global_limit
        if search_limit := os.getenv("SEARCH_RATE_LIMIT"):
            self.search_rate_limit = search_limit
        if export_limit := os.getenv("EXPORT_RATE_LIMIT"):
            self.export_rate_limit = export_limit
        if sources_limit := os.getenv("SOURCES_RATE_LIMIT"):
            self.sources_rate_limit = sources_limit
        if llm_limit := os.getenv("LLM_RATE_LIMIT"):
            self.llm_rate_limit = llm_limit
        
        # Security
        if cors_origins := os.getenv("ALLOWED_ORIGINS", os.getenv("CORS_ORIGINS")):
            self.cors_origins = cors_origins
        if cors_credentials := os.getenv("CORS_ALLOW_CREDENTIALS"):
            self.cors_allow_credentials = cors_credentials.lower() == "true"
        # (SEC-02) SECRET_KEY/CSRF_SECRET/JWT_* env reads removed: unused by any code.

        # Logging
        if log_level := os.getenv("LOG_LEVEL"):
            self.log_level = log_level
        if log_file := os.getenv("LOG_FILE"):
            self.log_file = log_file
        if audit_enabled := os.getenv("AUDIT_ENABLED"):
            self.audit_enabled = audit_enabled.lower() == "true"
        if audit_log_dir := os.getenv("AUDIT_LOG_DIR"):
            self.audit_log_dir = audit_log_dir
        if custody_on_ingest := os.getenv("OO_CUSTODY_ON_INGEST"):
            self.custody_on_ingest = custody_on_ingest.lower() in ("1", "true", "yes")

        # LLM
        if ollama_host := os.getenv("OLLAMA_HOST"):
            self.ollama_host = ollama_host
        if ollama_origins := os.getenv("OLLAMA_ORIGINS"):
            self.ollama_origins = ollama_origins
        if ollama_base_url := os.getenv("OLLAMA_BASE_URL"):
            self.ollama_base_url = ollama_base_url
        if auto_download := os.getenv("AUTO_DOWNLOAD_MODELS"):
            self.auto_download_models = auto_download.lower() == "true"
        if download_default := os.getenv("DOWNLOAD_DEFAULT_MODELS"):
            self.download_default_models = download_default.lower() == "true"
        if llm_timeout := os.getenv("LLM_TIMEOUT"):
            self.llm_timeout = int(llm_timeout)
        if llm_max_tokens := os.getenv("LLM_MAX_TOKENS"):
            self.llm_max_tokens = int(llm_max_tokens)
        
        # App
        if app_name := os.getenv("APP_NAME"):
            self.app_name = app_name
        if app_version := os.getenv("APP_VERSION"):
            self.app_version = app_version
        if debug := os.getenv("APP_DEBUG", os.getenv("DEBUG")):
            self.app_debug = debug.lower() == "true"
        if environment := os.getenv("ENVIRONMENT", os.getenv("APP_ENV")):
            self.app_environment = environment
    
    def _load_yaml_files(self):
        """Load configuration from YAML files."""
        configs_dir = self.repo_root / "configs"
        
        # Load settings.yaml
        settings_file = configs_dir / "settings.yaml"
        if settings_file.exists():
            try:
                with open(settings_file) as f:
                    settings = yaml.safe_load(f)
                    self._apply_yaml_config(settings)
            except Exception as e:
                logger.warning(f"Failed to load settings.yaml: {e}")
        
        # Load sources.yml (store in extra for use by other modules)
        sources_file = configs_dir / "sources.yml"
        if sources_file.exists():
            try:
                with open(sources_file) as f:
                    sources_config = yaml.safe_load(f)
                    self.extra["sources"] = sources_config.get("sources", [])
            except Exception as e:
                logger.warning(f"Failed to load sources.yml: {e}")
    
    def _apply_yaml_config(self, config: dict[str, Any]):
        """Apply configuration from a YAML dictionary."""
        if not config:
            return
        
        # Map YAML keys to config fields
        config_map = {
            "database": {"url": "database_url", "echo": "database_echo"},
            "scraping": {
                "max_workers": "max_workers",
                "max_retries": "max_retries",
                "initial_retry_delay": "initial_retry_delay",
                "timeout": "timeout",
                "user_agent": "user_agent",
                "rate_limit_ms": "rate_limit_ms",
            },
            "rate_limiting": {
                "global_rate_limit": "global_rate_limit",
                "search_rate_limit": "search_rate_limit",
                "export_rate_limit": "export_rate_limit",
                "sources_rate_limit": "sources_rate_limit",
            },
            "security": {
                "cors_origins": "cors_origins",
                "cors_allow_credentials": "cors_allow_credentials",
                "cors_allow_methods": "cors_allow_methods",
                "cors_allow_headers": "cors_allow_headers",
            },
            "logging": {
                "level": "log_level",
                "log_file": "log_file",
                "audit_enabled": "audit_enabled",
                "audit_log_dir": "audit_log_dir",
            },
            "llm": {
                "host": "ollama_host",
                "origins": "ollama_origins",
                "base_url": "ollama_base_url",
                "auto_download_models": "auto_download_models",
                "download_default_models": "download_default_models",
            },
            "app": {
                "name": "app_name",
                # version is intentionally NOT mapped: it is single-sourced from
                # package metadata via _package_version() (finding BUG-03), so a
                # stale literal in settings.yaml can no longer override it.
                "debug": "app_debug",
                "environment": "app_environment",
            },
        }
        
        for yaml_section, field_map in config_map.items():
            if yaml_section in config:
                yaml_config = config[yaml_section]
                if yaml_config:
                    for yaml_key, config_field in field_map.items():
                        if yaml_key in yaml_config and hasattr(self, config_field):
                            setattr(self, config_field, yaml_config[yaml_key])
    
    def _validate(self):
        """Validate configuration values."""
        # Ensure database URL is set
        if not self.database_url:
            raise ValueError("Database URL is not configured")
        
        # Ensure repo_root exists
        if not self.repo_root.exists():
            raise ValueError(f"Repository root {self.repo_root} does not exist")
    
    def get_database_url(self) -> str:
        """Get the database URL, ensuring it's an absolute path for SQLite."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            # Convert relative path to absolute
            relative_path = url.replace("sqlite:///", "")
            absolute_path = (self.repo_root / relative_path).resolve()
            return f"sqlite:///{absolute_path}"
        return url
    
    def get_sources_config_path(self) -> Path:
        """Get the path to the sources configuration file."""
        return self.repo_root / "configs" / "sources.yml"
    
    def get_data_dir(self) -> Path:
        """Get the data directory path."""
        data_dir = self.repo_root / "data"
        data_dir.mkdir(exist_ok=True, parents=True)
        return data_dir
    
    def get_audit_dir(self) -> Path:
        """Get the audit directory path."""
        audit_dir = self.repo_root / self.audit_log_dir
        audit_dir.mkdir(exist_ok=True, parents=True)
        return audit_dir
    
    def get_logs_dir(self) -> Path:
        """Get the logs directory path."""
        logs_dir = self.repo_root / "logs"
        logs_dir.mkdir(exist_ok=True, parents=True)
        return logs_dir


# Global configuration instance
_config: Config | None = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    Returns:
        Config: The global configuration instance.
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config():
    """Reset the global configuration instance (useful for testing)."""
    global _config
    _config = None


# Convenience function to get database URL
def get_database_url() -> str:
    """Get the database URL from configuration."""
    return get_config().get_database_url()


# Convenience function to get sources config path
def get_sources_config_path() -> Path:
    """Get the sources configuration file path."""
    return get_config().get_sources_config_path()
