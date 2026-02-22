# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""HTTP server entrypoint: FastAPI app for launching agents and tasks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import typer

from deadend_agent import DeadEndAgent, set_event_hooks
from deadend_agent.tools.tool_wrappers import set_approval_provider

from deadend_cli.cli_logging import logger
from deadend_cli.component_manager import ComponentManager
from deadend_cli.http import create_app
from deadend_cli.jsonrpc.event_bus import EventBus
from deadend_cli.jsonrpc.hooks_adapter import EventBusHooksAdapter


def _running_inside_container() -> bool:
    """Heuristic: True if this process is likely running inside a container."""
    return Path("/.dockerenv").exists() or os.environ.get("container") is not None


def _check_docker_socket_for_sandbox() -> None:
    """When running in a container, verify Docker socket is available for shell sandbox."""
    if not _running_inside_container():
        return
    sock = os.environ.get("DOCKER_HOST", "/var/run/docker.sock")
    if sock.startswith("unix://"):
        sock = sock.removeprefix("unix://")
    if not Path(sock).exists():
        logger.warning(
            "HTTP server is running inside a container but Docker socket is not visible at %s. "
            "Mount the host socket to enable shell sandbox: -v /var/run/docker.sock:/var/run/docker.sock",
            sock,
        )
        return
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.close()
        logger.info(
            "Docker socket available; shell sandbox can be used. "
            "Sandbox network is configurable via DOCKER_SANDBOX_NETWORK (default: host)."
        )
    except Exception as e:
        err_msg = str(e).lower()
        if "permission denied" in err_msg or isinstance(e, PermissionError):
            logger.warning(
                "Docker socket present but permission denied. To allow shell sandbox, run the container with "
                "the host docker group: docker run --group-add $(stat -c '%%g' /var/run/docker.sock) ... "
                "Or run the container as root. Error: %s",
                e,
            )
        else:
            logger.warning(
                "Docker socket present but daemon unreachable: %s. Shell sandbox may fail until Docker is available.",
                e,
            )


def main(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    log_file: str | None = typer.Option(None, "--log-file", help="Log file path (default: stderr only)"),
) -> None:
    """Start the HTTP API server for agents and tasks.

    This server exposes the same capabilities as the JSON-RPC server over REST:
    component init/health, event streaming, approval workflow, and agent/task execution.

    Running in Docker:
      For the shell sandbox to start and operate correctly, the host Docker socket
      must be mounted so the server can create sandbox containers, e.g.:
        docker run -v /var/run/docker.sock:/var/run/docker.sock ...
      Optional: set DOCKER_SANDBOX_NETWORK to the Docker network for sandbox
      containers (default: "host").
    """
    import logging

    from deadend_cli.cli_logging import setup_logging

    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, log_file=log_file)
    logger.info("HTTP server starting on %s:%s", host, port)

    _check_docker_socket_for_sandbox()

    component_manager = ComponentManager()
    event_bus = EventBus()
    hooks_adapter = EventBusHooksAdapter(event_bus=event_bus)

    set_event_hooks(hooks_adapter)
    set_approval_provider(event_bus)

    deadend_agent_refs: Dict[str, DeadEndAgent] = {}

    app = create_app(
        component_manager=component_manager,
        event_bus=event_bus,
        deadend_agent_refs=deadend_agent_refs,
    )

    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
    )


def run() -> None:
    """Entry point for the console script: ensures Typer parses argv and passes real values to main."""
    typer.run(main)


if __name__ == "__main__":
    run()
