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
Centralized Logging Configuration for Open Omniscience

This module provides a standardized logging setup for all components,
including file and console logging with consistent formatting.

Author: Ideotion
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ensure audit directory exists
AUDIT_DIR = Path(__file__).parent.parent.parent / "audit"
AUDIT_DIR.mkdir(exist_ok=True, parents=True)


def setup_logging(
    name: str, log_file: str | None = None, level: int = logging.INFO
) -> logging.Logger:
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
        encoding="utf-8",
    )
    file_handler.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Example usage
if __name__ == "__main__":
    # Test logger
    logger = setup_logging("test")
    logger.info("This is a test log message.")
