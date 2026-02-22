# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Component initialization endpoints."""

from fastapi import APIRouter, Depends

from deadend_cli.component_manager import ComponentManager
from deadend_cli.jsonrpc.rpc_models import AllInitResult, InitResult

from ..deps import get_component_manager

router = APIRouter(prefix="/init", tags=["init"])


@router.post("", response_model=AllInitResult)
async def init_all(component_manager: ComponentManager = Depends(get_component_manager)) -> AllInitResult:
    """Initialize all components in the correct order."""
    return await component_manager.init_all()


@router.post("/docker", response_model=InitResult)
async def init_docker(component_manager: ComponentManager = Depends(get_component_manager)) -> InitResult:
    """Initialize Docker client."""
    return await component_manager.init_docker()


@router.post("/pgvector", response_model=InitResult)
async def init_pgvector(component_manager: ComponentManager = Depends(get_component_manager)) -> InitResult:
    """Initialize pgvector database."""
    return await component_manager.init_pgvector()


@router.post("/config", response_model=InitResult)
async def init_config(component_manager: ComponentManager = Depends(get_component_manager)) -> InitResult:
    """Initialize configuration."""
    return await component_manager.init_config()


@router.post("/model-registry", response_model=InitResult)
async def init_model_registry(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> InitResult:
    """Initialize model registry."""
    return await component_manager.init_model_registry()


@router.post("/python-sandbox", response_model=InitResult)
async def init_python_sandbox(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> InitResult:
    """Initialize Python sandbox."""
    return await component_manager.init_python_sandbox()


@router.post("/shell-sandbox", response_model=InitResult)
async def init_shell_sandbox(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> InitResult:
    """Initialize shell sandbox."""
    return await component_manager.init_shell_sandbox()


@router.post("/playwright", response_model=InitResult)
async def init_playwright(
    component_manager: ComponentManager = Depends(get_component_manager),
) -> InitResult:
    """Initialize Playwright browser."""
    return await component_manager.init_playwright()
