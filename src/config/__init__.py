"""
Open Omniscience - Configuration Module

Centralized configuration management for the Open Omniscience platform.
This module provides a unified way to access configuration settings from
environment variables and YAML files.

Usage:
    from src.config import get_config, get_database_url
    
    config = get_config()
    db_url = config.get_database_url()
    
    # Or use convenience functions
    db_url = get_database_url()

Author: Ideotion
License: GNU GPLv3
"""

from .settings import (
    Config,
    get_config,
    reset_config,
    get_database_url,
    get_sources_config_path,
)

__all__ = [
    "Config",
    "get_config",
    "reset_config",
    "get_database_url",
    "get_sources_config_path",
]
