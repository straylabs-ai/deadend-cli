# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""AI model registry for managing different language model providers.

This module provides a registry system for managing AI model instances from
various providers (OpenAI, Anthropic, Google), including configuration,
initialization, and provider-specific model abstractions.
"""

from typing import Dict
import aiohttp
import numpy as np
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider

from deadend_agent.config.settings import Config
# AIModel abstraction
AIModel = OpenAIChatModel | AnthropicModel | GoogleModel

class EmbedderClient:
    model: str
    api_key: str 
    base_url: str

    def __init__(self, model_name: str, api_key: str, base_url: str) -> None:
        self.model = model_name
        self.api_key = api_key
        self.base_url = base_url

    async def batch_embed(self, input: list) -> list:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                    url=self.base_url,
                    headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "input": input
                    }
                )
            data = await response.json()
            embeddings = data['data']
        return embeddings if embeddings else []

class ModelRegistry:
    embedder_model: EmbedderClient | None 

    def __init__(self, config: Config):
        self._models: Dict[str, AIModel] = {}
        self._initialize_models(config=config)

    def _initialize_models(self, config: Config):
        models_settings = config.get_models_settings()
        if models_settings.openai:
            openai_settings = models_settings.openai
            self._models['openai'] = OpenAIChatModel(
                model_name=openai_settings.model_name,
                provider=OpenAIProvider(api_key=openai_settings.api_key)
            )
            self.embedder_model = EmbedderClient(
                model_name=config.embedding_model,
                api_key=config.openai_api_key,
                base_url="https://api.openai.com/v1/embeddings"
            )

        if models_settings.anthropic:
            anthropic_settings = models_settings.anthropic
            self._models['anthropic'] = AnthropicModel(
                model_name=anthropic_settings.model_name,
                provider=AnthropicProvider(api_key=anthropic_settings.api_key)
            )
            self.embedder_model = EmbedderClient(
                model_name=config.embedding_model,
                api_key=config.openai_api_key,
                base_url="https://api.openai.com/v1/embeddings"
            )


        if models_settings.gemini:
            gemini_settings = models_settings.gemini
            self._models['gemini'] = GoogleModel(
                model_name=gemini_settings.model_name,
                provider=GoogleProvider(api_key=gemini_settings.api_key),
            )
            self.embedder_model = EmbedderClient(
                model_name=config.embedding_model,
                api_key=config.openai_api_key,
                base_url="https://api.openai.com/v1/embeddings"
            )

        if models_settings.openrouter:
            openrouter_settings = models_settings.openrouter
            self._models['openrouter'] = OpenAIChatModel(
                model_name=openrouter_settings.model_name,
                provider=OpenAIProvider(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=openrouter_settings.api_key
                ),
            )
            self.embedder_model = EmbedderClient(
                model_name="openai/text-embedding-3-small",
                api_key=config.open_router_key,
                base_url="https://openrouter.ai/api/v1/embeddings"
            )
        
    def get_model(self, provider: str = 'openai') -> AIModel:
        print(self._models)
        if provider not in self._models:
            raise ValueError(f"Model provider {provider} not supported.")
        elif self._models == {}:
            raise ValueError("No model was instantiated. Have you tried supplying an API key for the Model?")
        return self._models[provider]

    def get_embedder_model(self):
        if self.embedder_model is None:
            raise ValueError(f"Embedder client could not be initialized: {self.embedder_model}")
        return self.embedder_model

    def list_configured_providers(self) -> list[str]:
        return list(self._models.keys())

    def has_any_model(self) -> bool:
        """Return True if at least one model provider is configured."""
        return len(self._models) > 0

    # Evaluation
    def get_all_models(self) -> Dict[str, AIModel]:
        return self._models.copy()

