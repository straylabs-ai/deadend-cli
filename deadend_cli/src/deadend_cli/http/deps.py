# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""FastAPI dependencies for the HTTP API (state injected at app creation)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from fastapi import Request

if TYPE_CHECKING:
    from deadend_agent import DeadEndAgent

    from deadend_cli.component_manager import ComponentManager
    from deadend_cli.jsonrpc.event_bus import EventBus


def get_component_manager(request: Request) -> "ComponentManager":
    """Get ComponentManager from app state."""
    return request.app.state.component_manager


def get_event_bus(request: Request) -> "EventBus":
    """Get EventBus from app state."""
    return request.app.state.event_bus


def get_agent_refs(request: Request) -> Dict[str, "DeadEndAgent"]:
    """Get agent refs dict from app state."""
    return request.app.state.deadend_agent_refs
