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
import platform
import subprocess
import requests
from deadend_agent.config.settings import Config
from deadend_agent.models.registry import ModelRegistry
from deadend_agent.sandbox.sandbox_manager import SandboxManager
from deadend_agent.rag.session_manager import RagSessionManager

def config_setup() -> Config:
    """Setup config"""
    config = Config()
    config.configure()
    # Populates the providers from the config.toml
    config.populate_providers()
    return config

def init_rag_session_manager(
    storage_root: str | Path | None = None,
) -> RagSessionManager:
    """Create a ``RagSessionManager`` backed by SQLite files.

    Args:
        storage_root: Root directory for agent session databases.
            Defaults to ``~/.cache/deadend/agents``.
    """
    root = Path(storage_root) if storage_root else Path.home() / ".cache" / "deadend" / "agents"
    root.mkdir(parents=True, exist_ok=True)
    return RagSessionManager(storage_root=root)

def sandbox_setup() -> SandboxManager:
    """Setup Sandbox manager"""
    # Sandbox Manager
    sandbox_manager = SandboxManager()
    return sandbox_manager

def setup_model_registry(config: Config) -> ModelRegistry:
    """Setup Model registry"""
    model_registry = ModelRegistry(config=config)
    return model_registry