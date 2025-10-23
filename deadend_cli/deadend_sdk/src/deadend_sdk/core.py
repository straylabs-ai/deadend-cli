# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core initialization and setup functions for the security research framework.

This module provides core initialization functions for setting up configuration,
database connections, sandbox environments, and model registries required
for the security research framework to operate.
"""

from deadend_sdk.config.settings import Config
from deadend_sdk.models.registry import ModelRegistry
from deadend_sdk.sandbox.sandbox_manager import SandboxManager
from deadend_sdk.rag.db_cruds import RetrievalDatabaseConnector

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