# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Re-export centralized logging from deadend_agent.

This module re-exports the logging utilities from deadend_agent.logging
for backwards compatibility and convenience.

Usage:
    from deadend_cli.logging import logger, setup_logging

    # Setup logging at startup (typically in RPC server or main)
    setup_logging(level=logging.DEBUG)

    # Use logger anywhere
    logger.debug("Debug message")
    logger.info("Info message")
"""

from deadend_agent.logging import (
    logger,
    setup_logging,
    get_module_logger,
    LOGGER_NAME,
)

__all__ = ["logger", "setup_logging", "get_module_logger", "LOGGER_NAME"]
