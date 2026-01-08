# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core initialization and setup functions for the security research framework.

This module provides core initialization functions for setting up configuration,
database connections, sandbox environments, and model registries required
for the security research framework to operate.
"""

from pathlib import Path
import hashlib
import subprocess
import requests
from deadend_agent.config.settings import Config
from deadend_agent.models.registry import ModelRegistry
from deadend_agent.sandbox.sandbox_manager import SandboxManager
from deadend_agent.rag.db_cruds import RetrievalDatabaseConnector


PYTHON_SANDBOX_NAME = "python-sandbox-tool-linux"
SIMPLE_PYTHON_SANDBOX_URL = (
    "https://github.com/xoxruns/simple-python-interpreter-sandbox/"
    "releases/download/v0.0.3/python-sandbox-tool-linux"
)
PYTHON_SANDBOX_SHA256 = "74b8a80709a912028600f39b9953889c011278a80acf066af5bd6979366455f4"

def config_setup() -> Config:
    """Setup config"""
    config = Config()
    config.configure()
    return config

async def init_rag_database(database_url: str) -> RetrievalDatabaseConnector:
    """Initialize RAG database"""
    # Check database connection and raise exception
    # if not connected
    rag_database = RetrievalDatabaseConnector(database_url=database_url)
    await rag_database.initialize_database()
    return rag_database

def sandbox_setup() -> SandboxManager:
    """Setup Sandbox manager"""
    # Sandbox Manager
    sandbox_manager = SandboxManager()
    return sandbox_manager

def setup_model_registry(config: Config) -> ModelRegistry:
    """Setup Model registry"""
    model_registry = ModelRegistry(config=config)
    return model_registry

def _file_matches_sha256(path: Path, expected_hash: str) -> bool:
    """Return True if the file exists and matches the expected SHA-256 hash."""
    if not path.exists():
        return False

    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_hash


def download_python_sandbox(
    destination_dir: Path | None = None,
    expected_sha256: str = PYTHON_SANDBOX_SHA256,
) -> Path:
    """Download the Python sandbox binary to the local cache if missing or outdated.

    Args:
        destination_dir: Optional directory to store the sandbox binary. Defaults
            to ~/.cache/deadend/python/.
        expected_sha256: Expected SHA-256 checksum of the binary.

    Returns:
        Path to the downloaded (or existing) sandbox binary.
    """
    cache_dir = destination_dir or Path.home() / ".cache" / "deadend" / "python"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sandbox_path = cache_dir / PYTHON_SANDBOX_NAME

    if _file_matches_sha256(sandbox_path, expected_sha256):
        return sandbox_path

    if sandbox_path.exists():
        sandbox_path.unlink()

    response = requests.get(SIMPLE_PYTHON_SANDBOX_URL, stream=True, timeout=120)
    response.raise_for_status()
    with open(sandbox_path, "wb") as fd:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                fd.write(chunk)

    if not _file_matches_sha256(sandbox_path, expected_sha256):
        sandbox_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded Python sandbox binary failed checksum verification."
        )

    sandbox_path.chmod(0o744)
    return sandbox_path


def start_python_sandbox(
    cache_dir: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Ensure the sandbox binary exists and start it in the background.

    Args:
        cache_dir: Optional override for the sandbox cache directory.

    Returns:
        subprocess.Popen: Handle to the running sandbox process.
    """
    cache_dir = cache_dir or Path.home() / ".cache" / "deadend" / "python"
    sandbox_path = download_python_sandbox(destination_dir=cache_dir)
    process = subprocess.Popen(
        [str(sandbox_path)],
        cwd=str(cache_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process
