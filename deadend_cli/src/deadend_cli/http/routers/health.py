# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Health check endpoints."""

from fastapi import APIRouter, Depends

from deadend_cli.component_manager import ComponentManager
from deadend_cli.jsonrpc.rpc_models import AllHealthResult, HealthResult

from ..deps import get_component_manager

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=AllHealthResult)
async def health_all(component_manager: ComponentManager = Depends(get_component_manager)) -> AllHealthResult:
    """Check health of all components."""
    return await component_manager.health_all()


@router.get("/docker", response_model=HealthResult)
async def health_docker(component_manager: ComponentManager = Depends(get_component_manager)) -> HealthResult:
    """Check Docker daemon health."""
    return await component_manager.health_docker()


@router.get("/pgvector", response_model=HealthResult)
async def health_pgvector(component_manager: ComponentManager = Depends(get_component_manager)) -> HealthResult:
    """Check pgvector database health."""
    return await component_manager.health_pgvector()


@router.get("/python-sandbox", response_model=HealthResult)
async def health_python_sandbox(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> HealthResult:
    """Check Python sandbox health."""
    return await component_manager.health_python_sandbox()


@router.get("/shell-sandbox", response_model=HealthResult)
async def health_shell_sandbox(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> HealthResult:
    """Check shell sandbox health."""
    return await component_manager.health_shell_sandbox()


@router.get("/playwright", response_model=HealthResult)
async def health_playwright(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> HealthResult:
    """Check Playwright browser health."""
    return await component_manager.health_playwright()
