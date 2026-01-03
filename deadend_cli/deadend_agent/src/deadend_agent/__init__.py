# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core framework for automated security research and web application testing.

This module provides the main framework components including configuration
management, database initialization, sandbox setup, and model registry
for the security research CLI application.
"""

from .config.settings import Config
from .core import config_setup, init_rag_database, sandbox_setup, setup_model_registry
from .models.registry import ModelRegistry, AIModel
from .rag.db_cruds import RetrievalDatabaseConnector
from .sandbox.sandbox import Sandbox
from .deadend_agent import DeadEndAgent
from .hooks import (
    EventHooks,
    NullEventHooks,
    set_event_hooks,
    get_event_hooks,
)


__all__ = [
    'DeadEndAgent',
    'Config',
    'ModelRegistry',
    'AIModel',
    'RetrievalDatabaseConnector',
    'Sandbox',
    'config_setup',
    'init_rag_database',
    'sandbox_setup',
    'setup_model_registry',
    # Hooks
    'EventHooks',
    'NullEventHooks',
    'set_event_hooks',
    'get_event_hooks',
]

