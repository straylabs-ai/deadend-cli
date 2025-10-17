# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""CLI initialization module.

This module provides functionality to initialize the CLI configuration
by prompting for environment variables and saving them to a cache TOML file.
"""

import os
import time
from pathlib import Path
import toml
import typer
import docker
from docker.errors import DockerException, NotFound
from rich.console import Console

console = Console()


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


def check_pgvector_container(client: docker.DockerClient) -> bool:
    """Check if pgvector container is running.
    
    Args:
        client: Docker client instance
        
    Returns:
        bool: True if pgvector container is running, False otherwise
    """
    try:
        container = client.containers.get("deadend_pg")
        return container.status == "running"
    except NotFound:
        return False
    except DockerException as e:
        console.print(f"[yellow]Warning: Could not check pgvector container status: {e}[/yellow]")
        return False


def setup_pgvector_database(client: docker.DockerClient) -> bool:
    """Setup pgvector database using Docker API.
    
    Args:
        client: Docker client instance
        
    Returns:
        bool: True if setup successful, False otherwise
    """
    try:
        # Check if container already exists
        try:
            existing_container = client.containers.get("deadend_pg")
            if existing_container.status == "running":
                console.print("[green]pgvector database is already running.[/green]")
                return True
            else:
                console.print("[yellow]Found existing pgvector container, starting it...[/yellow]")
                existing_container.start()
                # Wait for container to be ready
                time.sleep(5)
                console.print("[green]pgvector database started successfully.[/green]")
                return True
        except NotFound:
            pass  # Container doesn't exist, create new one

        # Create postgres_data directory in cache if it doesn't exist
        cache_dir = Path.home() / ".cache" / "deadend"
        postgres_data_dir = cache_dir / "postgres_data"
        postgres_data_dir.mkdir(parents=True, exist_ok=True)

        console.print("[blue]Setting up pgvector database...[/blue]")

        # Pull the pgvector image
        console.print("Pulling pgvector image...")
        client.images.pull("pgvector/pgvector:pg17")

        # Create and run the container
        container = client.containers.run(
            "pgvector/pgvector:pg17",
            name="deadend_pg",
            environment={
                "POSTGRES_DB": "codeindexerdb",
                "POSTGRES_USER": "postgres", 
                "POSTGRES_PASSWORD": "postgres"
            },
            ports={"5432/tcp": 54320},
            volumes={str(postgres_data_dir): {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
            detach=True,
            remove=False
        )

        # Wait for container to be ready
        console.print("Waiting for database to be ready...")
        time.sleep(10)

        # Check if container is running
        container.reload()
        if container.status == "running":
            console.print("[green]pgvector database setup completed successfully.[/green]")
            console.print("[blue]Database connection: postgresql://postgres:postgres@localhost:54320/codeindexerdb[/blue]")
            return True
        else:
            console.print(f"[red]Failed to start pgvector container. Status: {container.status}[/red]")
            return False
            
    except DockerException as e:
        console.print(f"[red]Error setting up pgvector database: {e}[/red]")
        return False
    except (OSError, ConnectionError) as e:
        console.print(f"[red]Connection error setting up pgvector: {e}[/red]")
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


def stop_pgvector_container(client: docker.DockerClient) -> bool:
    """Stop the pgvector container.
    
    Args:
        client: Docker client instance
        
    Returns:
        bool: True if stopped successfully, False otherwise
    """
    try:
        container = client.containers.get("deadend_pg")
        if container.status == "running":
            console.print("[blue]Stopping pgvector database...[/blue]")
            container.stop()
            console.print("[green]pgvector database stopped successfully.[/green]")
            return True
        else:
            console.print("[yellow]pgvector container is not running.[/yellow]")
            return True
    except NotFound:
        console.print("[yellow]pgvector container not found.[/yellow]")
        return True
    except DockerException as e:
        console.print(f"[red]Error stopping pgvector container: {e}[/red]")
        return False
    except (OSError, ConnectionError) as e:
        console.print(f"[red]Connection error stopping pgvector: {e}[/red]")
        return False


def init_cli_config():
    """Initialize CLI config by prompting for env vars and saving to cache TOML.

    Writes to ~/.cache/deadend/config.toml
    
    Returns:
        Path: The path to the created configuration file
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
        console.print("\n[red]Docker is required for this application to function properly.[/red]")
        console.print("Please install and start Docker, then run this command again.")
        raise typer.Exit(1)
    
    # Check and setup pgvector database
    if not check_pgvector_container(docker_client):
        console.print("\n[blue]pgvector database not found. Setting up...[/blue]")
        if not setup_pgvector_database(docker_client):
            console.print("\n[red]Failed to setup pgvector database.[/red]")
            console.print("Please check Docker logs and try again.")
            raise typer.Exit(1)
    else:
        console.print("[green]pgvector database is already running.[/green]")
    
    # Pull sandboxed Kali image
    console.print("\n[blue]Setting up sandboxed Kali image...[/blue]")
    if not pull_sandboxed_kali_image(docker_client):
        console.print("\n[yellow]Warning: Failed to pull sandboxed Kali image.[/yellow]")
        console.print("Some features may not work properly. You can try again later.")
    
    cache_dir = Path.home() / ".cache" / "deadend"
    cache_dir.mkdir(parents=True, exist_ok=True)
    config_file = cache_dir / "config.toml"

    # Check if config file already exists and is populated
    if config_file.exists():
        try:
            with config_file.open("r") as f:
                existing_config = toml.load(f)
            
            # Check if config has essential keys and values
            essential_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
            has_essential_config = any(
                existing_config.get(key, "").strip() 
                for key in essential_keys
            )
            
            if has_essential_config:
                console.print("[green]Configuration file already exists and is populated.[/green]")
                console.print(f"Config file: {config_file}")
                console.print("If you need to update the configuration, delete the file and run init again.")
                return config_file
            else:
                console.print("[yellow]Configuration file exists but appears to be empty or incomplete.[/yellow]")
                console.print("Proceeding with configuration setup...")
        except (toml.TomlDecodeError, OSError) as e:
            console.print(f"[yellow]Warning: Could not read existing config file: {e}[/yellow]")
            console.print("Proceeding with configuration setup...")

    # Read current environment as defaults
    defaults = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o-mini-2024-07-18"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_MODEL": os.getenv("ANTHROPIC_MODEL", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", ""),
        "DB_URL": os.getenv("DB_URL", ""),
        "ZAP_PROXY_API_KEY": os.getenv("ZAP_PROXY_API_KEY", ""),
        "APP_ENV": os.getenv("APP_ENV", "development"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
    }

    console.print("Configure environment values (press Enter to keep defaults).")
    values = {}
    prompts = [
        ("OPENAI_API_KEY", True),
        ("OPENAI_MODEL", False),
        ("ANTHROPIC_API_KEY", True),
        ("ANTHROPIC_MODEL", False),
        ("GEMINI_API_KEY", True),
        ("GEMINI_MODEL", False),
        ("EMBEDDING_MODEL", False),
        ("DB_URL", False),
        ("ZAP_PROXY_API_KEY", True),
        ("APP_ENV", False),
        ("LOG_LEVEL", False),
    ]

    for key, hide in prompts:
        values[key] = typer.prompt(
            key,
            default=defaults.get(key, ""),
            hide_input=hide,
        )

    with config_file.open("w") as f:
        toml.dump(values, f)

    console.print(f"Saved configuration to {config_file}")
    return config_file
