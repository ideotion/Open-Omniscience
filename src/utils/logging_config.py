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

from src.monitoring.secret_scrub import protect_handler

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

    # Add handlers. Each is behind the passphrase filter: a record any module writes through this logger (a
    # ``logger.exception`` among them) carries what the exception said, and the audit file keeps it.
    logger.addHandler(protect_handler(file_handler))
    logger.addHandler(protect_handler(console_handler))

    return logger


def uvicorn_log_config() -> dict:
    """The server's own logging configuration (``uvicorn.config.LOGGING_CONFIG``) with every one of its handlers behind the
    passphrase filter (``secret_scrub.SecretFilter``): the server writes the exception that escaped the application to the
    console as it made its message (``Exception in ASGI application``), and the console of a launcher can be a file. A copy,
    never the module's own dictionary: that is the server's, and a second server in the process would otherwise inherit it.

    The access handler's formatter is ours (``src/utils/access_log.py``): the server's unpacks five arguments from every record,
    and the filter hands it a record with none when it withheld the line or rewrote it as one text, which made the logging module
    print ``--- Logging error ---`` for each such request and write no access line."""
    import copy

    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["oo_passphrase"] = {"()": "src.monitoring.secret_scrub.SecretFilter"}
    for handler in config["handlers"].values():
        handler["filters"] = [*handler.get("filters", []), "oo_passphrase"]
    config["formatters"]["access"]["()"] = "src.utils.access_log.AccessFormatter"
    return config


# Example usage
if __name__ == "__main__":
    # Test logger
    logger = setup_logging("test")
    logger.info("This is a test log message.")
