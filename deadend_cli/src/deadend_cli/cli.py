# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Deadend CLI entrypoint using Typer.

Defines maintenance and evaluation commands for the Python package.
"""
import asyncio
import importlib.metadata
import os
import logging
import docker
import typer

from rich.console import Console
from deadend_agent import config_setup
from .cli_logging import setup_logging
from .init import init_cli_config, check_docker
from .eval import eval_interface

# Fix Docker socket path if default doesn't exist
if not os.path.exists("/var/run/docker.sock"):
    docker_socket = os.path.expanduser("~/.docker/run/docker.sock")
    if os.path.exists(docker_socket):
        os.environ["DOCKER_HOST"] = f"unix://{docker_socket}"


console = Console()

app = typer.Typer(help="Deadend CLI - Python maintenance and evaluation commands.")


@app.command()
def version():
    """Show the version of the Deadend framework."""
    try:
        package_version = importlib.metadata.version("deadend_cli")
        console.print(f"[bold green]Deadend CLI v{package_version}[/bold green]")
    except importlib.metadata.PackageNotFoundError:
        console.print(
            "[bold red]Deadend CLI[/bold red] - [yellow]Version not available[/yellow]"
        )


@app.command()
def eval_agent(
    eval_metadata_file: str = typer.Option(
        None,
        help="Dataset file containing all the information about the challenges to run",
    ),
    provider: str = typer.Option(
        default="azure_ai", help="Provider name"
    ),
    model_name: str = typer.Option(
        default="Kimi-K2.5", help="Model name"
    ),
    guided: bool = typer.Option(
        False, help="Run subtasks instead of one general task."
    ),
):
    """Run the evaluation agent on a dataset of challenges.

    Args:
        eval_metadata_file: Path to the dataset file describing challenges.
        llm_providers: List of model providers to use.
        guided: If True, run subtasks instead of a single general task.
    """
    # Init configurations
    # Check Docker availability first
    docker_client = docker.from_env()
    if not check_docker(docker_client):
        console.print(
            "\n[red]Docker is required for this application to function properly.[/red]"
        )
        console.print("Please install Docker from: https://docs.docker.com/get-docker/")
        console.print(
            "Make sure Docker daemon is running, then run this command again."
        )
        raise typer.Exit(1)

    config = config_setup()
    log_level_name = str(config.log_level or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    setup_logging(level=log_level)
    # start eval
    try:
        asyncio.run(
            eval_interface(
                config=config,
                eval_metadata_file=eval_metadata_file,
                provider=provider,
                model_name=model_name,
            )
        )
    finally:
        pass


@app.command()
def init():
    """Initialize CLI config by prompting for env vars and saving to cache JSON.

    Writes to ~/.cache/deadend/config.json
    """
    init_cli_config()
