"""
Shared Logging Configuration for Open Omniscience

This module provides a standardized logging setup for all components.

Author: Ideotion
"""

import logging
from pathlib import Path


def setup_logging(name: str) -> logging.Logger:
    """
    Set up a standardized logger for a module.
    
    Args:
        name: Name of the logger (used for the log file name).
        
    Returns:
        A configured logger instance.
    """
    # Ensure audit directory exists
    log_dir = Path(__file__).parent.parent.parent / "audit"
    log_dir.mkdir(exist_ok=True, parents=True)
    
    # Create log file path
    log_file = log_dir / f"{name}.log"
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger(name)