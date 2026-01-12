# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Centralized logging configuration for deadend.

This module provides a single logger instance and setup function
that can be used across all modules in deadend_agent and deadend_cli.
Logs are sent to stderr to avoid interfering with stdout-based protocols
like JSON-RPC.

Usage:
    from deadend_agent.logging import logger, setup_logging

    # Setup logging at startup (typically in RPC server or main)
    setup_logging(level=logging.DEBUG)

    # Use logger anywhere
    logger.debug("Debug message")
    logger.info("Info message")
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

# Package-wide logger name
LOGGER_NAME = "deadend"

# Create the package logger
logger = logging.getLogger(LOGGER_NAME)


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
) -> logging.Logger:
    """Configure the package-wide logger.

    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO).
               Defaults to INFO.
        log_file: Optional path to log file. If provided, logs will also
                  be written to this file.
        format_string: Custom format string for log messages.
                       If not provided, uses a sensible default.

    Returns:
        The configured logger instance.
    """
    # Set the level on the package logger
    logger.setLevel(level)

    # Default format
    if format_string is None:
        format_string = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"

    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()

    # Console handler (stderr for daemon-friendly operation)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent propagation to root logger (avoids duplicate logs)
    logger.propagate = False

    return logger


def get_module_logger(module_name: str) -> logging.Logger:
    """Get a child logger for a specific module.

    Args:
        module_name: Name of the module (typically __name__).

    Returns:
        A child logger that inherits settings from the package logger.

    Usage:
        module_logger = get_module_logger(__name__)
        module_logger.debug("Module-specific debug message")
    """
    return logging.getLogger(f"{LOGGER_NAME}.{module_name}")


__all__ = ["logger", "setup_logging", "get_module_logger", "LOGGER_NAME"]
