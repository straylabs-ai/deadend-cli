# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""LLM provider and model endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from deadend_cli.component_manager import ComponentManager

from ..deps import get_component_manager
from ..schemas import AddModelRequest, AddModelResponse, LlmProviderResponse, SetProviderRequest

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/models")
async def get_all_models(component_manager: ComponentManager = Depends(get_component_manager)):
    """List all available and configured models from config."""
    return component_manager.get_all_models()


@router.get("/provider", response_model=LlmProviderResponse)
async def get_llm_provider(component_manager: ComponentManager = Depends(get_component_manager)) -> LlmProviderResponse:
    """Get the current LLM provider and model name."""
    provider = component_manager.get_llm_provider()
    try:
        model_spec = component_manager.get_model(provider=provider)
        return LlmProviderResponse(provider=provider, model=model_spec.model_name)
    except (RuntimeError, ValueError):
        return LlmProviderResponse(provider=provider, model=None)


@router.post("/provider")
async def set_llm_provider(
    body: SetProviderRequest,
    component_manager: ComponentManager = Depends(get_component_manager),
):
    """Set the current LLM provider."""
    component_manager.set_llm_provider(body.provider)
    return {"status": "ok", "provider": body.provider}


@router.post("/models", response_model=AddModelResponse)
async def add_model(
    body: AddModelRequest,
    component_manager: ComponentManager = Depends(get_component_manager),
) -> AddModelResponse:
    """Add a new model provider to the configuration."""
    if component_manager.config is None:
        raise HTTPException(status_code=503, detail="Configuration not initialized")

    if not body.provider or not body.model_name:
        raise HTTPException(status_code=400, detail="provider and model_name are required")

    component_manager.add_model_provider(
        provider=body.provider,
        model_name=body.model_name,
        api_key=body.api_key,
        base_url=body.base_url,
        type_model=body.type_model,
        vec_dim=body.vec_dim,
    )

    if body.type_model != "embeddings" and component_manager.model_registry:
        try:
            component_manager.set_llm_provider(body.provider)
        except (ValueError, RuntimeError):
            pass

    return AddModelResponse(
        status="ok",
        provider=body.provider,
        model_name=body.model_name,
        type_model=body.type_model,
    )
