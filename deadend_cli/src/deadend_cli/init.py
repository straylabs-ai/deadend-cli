# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""CLI initialization module.

Performs the prerequisites that must be in place before the agent can run:
- ensure Docker is reachable
- pull the sandboxed Kali image used by the sandbox manager

Provider configuration (API keys, models, etc.) is *not* handled here. That
state lives in ``~/.deadend/config.json`` and is written by the
interactive provider selector exposed in the chat UI / RPC layer (see
``Config.add_provider`` / ``Config.update_provider``).
"""

import sys

import docker
import typer
from docker.errors import DockerException
from rich.console import Console

# Use stderr for console output so that stdout can remain reserved for
# machine-readable JSON when this module is used from the RPC server.
console = Console(file=sys.stderr)


def check_docker(client: docker.DockerClient) -> bool:
    """Check if Docker daemon is running using the Docker Python API.

    Args:
        client: Docker client instance

    Returns:
        bool: True if Docker daemon is available and running, False otherwise
    """
    try:
        # Ping the Docker daemon to check if it's responsive
        client.ping()
        return True
    except DockerException as e:
        console.print(f"[red]Docker is not available: {e}[/red]")
        console.print("Please install Docker from: https://docs.docker.com/get-docker/")
        console.print("Make sure Docker daemon is running.")
        return False
    except (OSError, ConnectionError) as e:
        console.print(f"[red]Connection error checking Docker: {e}[/red]")
        return False


def pull_sandboxed_kali_image(client: docker.DockerClient) -> bool:
    """Pull the sandboxed Kali image.

    Args:
        client: Docker client instance

    Returns:
        bool: True if pull successful, False otherwise
    """
    try:
        console.print("[blue]Pulling sandboxed Kali image...[/blue]")
        client.images.pull("xoxruns/sandboxed_kali")
        console.print("[green]Sandboxed Kali image pulled successfully.[/green]")
        return True
    except DockerException as e:
        console.print(f"[red]Error pulling sandboxed Kali image: {e}[/red]")
        return False
    except (OSError, ConnectionError) as e:
        console.print(f"[red]Connection error pulling sandboxed Kali image: {e}[/red]")
        return False


def init_cli_config() -> None:
    """Run the one-time CLI prerequisites (Docker availability + image pull).

    Provider/API-key configuration is handled separately through the chat UI
    and persisted to ``~/.deadend/config.json``.
    """
    # Create a single Docker client instance for all operations
    try:
        docker_client = docker.from_env()
    except DockerException as e:
        console.print(f"[red]Failed to initialize Docker client: {e}[/red]")
        console.print("Please install Docker from: https://docs.docker.com/get-docker/")
        console.print("Make sure Docker daemon is running.")
        raise typer.Exit(1)

    # Check Docker availability first - exit if not available
    if not check_docker(docker_client):
        console.print(
            "\n[red]Docker is required for this application to function properly.[/red]"
        )
        console.print("Please install and start Docker, then run this command again.")
        raise typer.Exit(1)

    # Pull sandboxed Kali image
    console.print("\n[blue]Setting up sandboxed Kali image...[/blue]")
    if not pull_sandboxed_kali_image(docker_client):
        console.print(
            "\n[yellow]Warning: Failed to pull sandboxed Kali image.[/yellow]"
        )
        console.print("Some features may not work properly. You can try again later.")

    console.print(
        "\n[green]Initialization complete.[/green] "
        "Configure LLM providers from the chat UI; "
        "they will be saved to ~/.deadend/config.json."
    )
