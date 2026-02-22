# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""FastAPI application factory for the HTTP API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING, Dict

from fastapi import Depends, FastAPI


def _get_api_version() -> str:
    """Return the deadend_cli package version for the API docs."""
    try:
        return _pkg_version("deadend_cli")
    except Exception:
        return "0.1.0"

from .deps import get_component_manager
from .routers import agents, events, health, init, llm

if TYPE_CHECKING:
    from deadend_agent import DeadEndAgent

    from deadend_cli.component_manager import ComponentManager
    from deadend_cli.jsonrpc.event_bus import EventBus


def create_app(
    component_manager: "ComponentManager",
    event_bus: "EventBus",
    deadend_agent_refs: Dict[str, "DeadEndAgent"],
):
    """Create the FastAPI app with shared state (components, event bus, agent refs)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: approval provider is set in main() before app runs
        yield
        # Shutdown: optional cleanup can be added here

    app = FastAPI(
        title="Deadend API",
        description="API for launching agents and tasks.",
        version=_get_api_version(),
        lifespan=lifespan,
    )

    app.state.component_manager = component_manager
    app.state.event_bus = event_bus
    app.state.deadend_agent_refs = deadend_agent_refs

    app.include_router(health.router)
    app.include_router(init.router)
    app.include_router(events.router)
    app.include_router(llm.router)
    app.include_router(agents.router)

    @app.get("/ping")
    async def ping():
        """Health ping."""
        return {"status": "ok"}

    @app.post("/shutdown")
    async def shutdown(cm=Depends(get_component_manager)):
        """Request graceful shutdown of all components. Caller may then exit the process."""
        result = await cm.shutdown()
        return {"status": "shutdown", "components": result}

    return app
