# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Main entry point for the security research CLI application.

This module serves as the primary entry point for the deadend-cli application,
providing the main function that initializes and runs the CLI interface
for security research and web application testing.
"""

import asyncio
import os
import shutil
from importlib.resources import files
from pathlib import Path

from dotenv import load_dotenv

from .jsonrpc.event_bus import EventBus, event_bus
from .component_manager import ComponentManager
from .jsonrpc.hooks_adapter import EventBusHooksAdapter
from .jsonrpc.rpc_models import (
    AgentEvent,
    EventType,
    ComponentStatus,
    ComponentState,
    InitResult,
    HealthResult,
    AllHealthResult,
    AllInitResult,
    RPCErrorCode,
)
from .cli_logging import logger, setup_logging, get_module_logger


def get_rpc_server():
    """Lazy import of RPCServer to avoid circular import issues when running as module."""
    from .jsonrpc.rpc_server import RPCServer
    return RPCServer

__all__ = [
    "main",
    "get_rpc_server",  # Use lazy import to avoid circular import issues
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
    "AllInitResult",
    "RPCErrorCode",
    # Logging
    "logger",
    "setup_logging",
    "get_module_logger",
]


def _load_env_files() -> None:
    """Load .env from cwd and optionally ~/.config/deadend/.env (later overrides)."""
    load_dotenv()  # cwd .env
    global_env = Path.home() / ".config" / "deadend" / ".env"
    if global_env.exists():
        load_dotenv(dotenv_path=global_env)

def _phoenix_otel_enabled() -> bool:
    """True if Phoenix OTLP should be used (from .env / env vars)."""
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "").strip()
    enabled = os.getenv("DEADEND_PHOENIX_OTEL_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return bool(endpoint) or enabled

def main():
    """Entry point for the deadend CLI application."""

    # Load .env so Phoenix/OTEL settings can be conditional
    _load_env_files()

    # copy reusable creds to cache
    try:
        source_creds = (
            files("deadend_cli")
            .joinpath("data")
            .joinpath("memory")
            .joinpath("reusable_credentials.json")
        )
        path_creds = Path(str(source_creds))
    except (ImportError, FileNotFoundError):
        print("not found.")
        path_creds = Path(__file__) / "data" / "memory" / "reusable_credentials.json"
    cache_dir = Path.home() / ".cache" / "deadend" / "memory"
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination_file = cache_dir / "reusable_credentials.json"
    if path_creds.exists():
        shutil.copy2(path_creds, destination_file)

    if _phoenix_otel_enabled():
        # Register Phoenix OTLP before importing the agent so the global tracer provider
        # is Phoenix; agent telemetry will then use it (see DEADEND_OTEL_USE_GLOBAL in telemetry.py).
        os.environ["DEADEND_OTEL_USE_GLOBAL"] = "1"
        from phoenix.otel import register

        endpoint = (os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or "https://crunch.straylabs.ai/").strip().rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint = f"{endpoint}/v1/traces"
        project_name = os.getenv("PHOENIX_PROJECT_NAME", "deadend")

        register(
            auto_instrument=True,
            project_name=project_name,
            batch=True,
            endpoint=endpoint,
            protocol="http/protobuf",
        )

    from .cli import app

    asyncio.run(app())

if __name__ == "__main__":
    main()