# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Main entry point for the security research CLI application.

This module serves as the primary entry point for the deadend-cli application,
providing the main function that initializes and runs the CLI interface
for security research and web application testing.
"""

import asyncio
import shutil
from importlib.resources import files
from pathlib import Path
from .cli import app
from .rpc_server import RPCServer
from .event_bus import EventBus, event_bus
from .component_manager import ComponentManager
from .hooks_adapter import EventBusHooksAdapter
from .rpc_models import (
    AgentEvent,
    EventType,
    ComponentStatus,
    ComponentState,
    InitResult,
    HealthResult,
    AllHealthResult,
    RPCErrorCode,
)

__all__ = [
    "main",
    "RPCServer",
    "EventBus",
    "event_bus",
    "ComponentManager",
    "EventBusHooksAdapter",
    "AgentEvent",
    "EventType",
    "ComponentStatus",
    "ComponentState",
    "InitResult",
    "HealthResult",
    "AllHealthResult",
    "RPCErrorCode",
]


def main():
    """Entry point for the deadend CLI application."""

    # copy reusable creds to cache
    try:
        source_creds = files("deadend_cli").joinpath("data", "memory", "reusable_credentials.json")
        path_creds = Path(str(source_creds))
    except (ImportError, FileNotFoundError):
        print("not found.")
        path_creds = Path(__file__) / "data" / "memory" / "reusable_credentials.json"
    cache_dir = Path.home() / ".cache" / "deadend" / "memory"
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination_file = cache_dir / "reusable_credentials.json"
    if path_creds.exists():
        shutil.copy2(path_creds, destination_file)

    asyncio.run(app())

if __name__ == "__main__":
    main()