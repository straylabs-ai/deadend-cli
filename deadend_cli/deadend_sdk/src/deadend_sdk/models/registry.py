# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""AI model registry for managing different language model providers.

This module provides a registry system for managing AI model instances from
various providers (OpenAI, Anthropic, Google), including configuration,
initialization, and provider-specific model abstractions.
"""

from typing import Dict
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider

from deadend_sdk.config.settings import Config
# AIModel abstraction
AIModel = OpenAIChatModel | AnthropicModel | GoogleModel

class ModelRegistry:
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
        
        if models_settings.anthropic:
            anthropic_settings = models_settings.anthropic
            self._models['anthropic'] = AnthropicModel(
                model_name=anthropic_settings.model_name,
                provider=AnthropicProvider(api_key=anthropic_settings.api_key)
            )

        if models_settings.gemini:
            gemini_settings = models_settings.gemini
            self._models['gemini'] = GoogleModel(
                model_name=gemini_settings.model_name,
                provider=GoogleProvider(api_key=gemini_settings.api_key),
            )

    def get_model(self, provider: str = 'openai') -> AIModel:
        if provider not in self._models:
            raise ValueError(f"Model provider {provider} not supported.")
        elif self._models == {}:
            raise ValueError("No model was instantiated. Have you tried supplying an API key for the Model?")
        return self._models[provider]

    def list_configured_providers(self) -> list[str]:
        return list(self._models.keys())

    def has_any_model(self) -> bool:
        """Return True if at least one model provider is configured."""
        return len(self._models) > 0

    # Evaluation
    def get_all_models(self) -> Dict[str, AIModel]:
        return self._models.copy()