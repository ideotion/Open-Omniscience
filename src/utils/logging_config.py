"""
Centralized Logging Configuration for Open Omniscience

This module provides a standardized logging setup for all components,
including file and console logging with consistent formatting.

Author: Ideotion
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone
import os

# Ensure audit directory exists
AUDIT_DIR = Path(__file__).parent.parent.parent / "audit"
AUDIT_DIR.mkdir(exist_ok=True, parents=True)


def setup_logging(name: str, log_file: str = None, level: int = logging.INFO) -> logging.Logger:
    """
    Set up a logger with file and console handlers.

    Args:
        name: Name of the logger (e.g., "scraper", "api").
        log_file: Name of the log file (default: {name}.log).
        level: Logging level (default: INFO).

    Returns:
        Configured logger instance.
    """
    if log_file is None:
        log_file = f"{name}.log"

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # File handler (rotating log)
    file_path = AUDIT_DIR / log_file
    file_handler = RotatingFileHandler(
        filename=file_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def log_audit_trail(action: str, details: dict, user: str = None):
    """
    Log an action to the central audit trail file.

    Args:
        action: Type of action (e.g., "scrape", "search", "export").
        details: Dictionary of details about the action.
        user: Optional user identifier (default: None for automated actions).
    """
    audit_file = AUDIT_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_OpenOmniscience_AUDIT_TRAIL.md"
    timestamp = datetime.now(timezone.utc).isoformat() + "Z"

    # Format details as a string
    details_str = ", ".join(f"{k}: {v}" for k, v in details.items())

    # Write to audit file
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(f"### {timestamp}\n")
        f.write(f"- **Action**: {action}\n")
        if user:
            f.write(f"- **User**: {user}\n")
        f.write(f"- **Details**: {details_str}\n\n")


# Example usage
if __name__ == "__main__":
    # Test logger
    logger = setup_logging("test")
    logger.info("This is a test log message.")

    # Test audit trail
    log_audit_trail(
        action="scrape",
        details={
            "source": "BBC News",
            "url": "https://bbc.com/news",
            "status": "success",
            "articles": 10
        }
    )