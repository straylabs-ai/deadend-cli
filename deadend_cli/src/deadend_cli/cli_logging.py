"""Re-export centralized logging from deadend_agent.

This module re-exports the logging utilities from deadend_agent.logging
for backwards compatibility and convenience, without shadowing the
standard library ``logging`` module.

Usage:
    from deadend_cli.cli_logging import logger, setup_logging

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


