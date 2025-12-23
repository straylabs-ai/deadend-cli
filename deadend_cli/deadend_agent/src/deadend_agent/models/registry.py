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
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.providers.azure import AzureProvider

from deadend_agent.config.settings import Config

# AIModel abstraction
AIModel = OpenAIChatModel | AnthropicModel | GoogleModel
"""Type alias for supported AI model providers.
    
This represents any of the supported language model types from OpenAI,
Anthropic, or Google providers.
"""

class EmbedderClient:
    """Client for generating embeddings using various embedding API providers.
    
    This class provides a unified interface for embedding generation across
    different providers (OpenAI, OpenRouter, etc.) by abstracting the API
    communication and response parsing.
    
    Attributes:
        model: Name of the embedding model to use.
        api_key: API key for authenticating with the embedding service.
        base_url: Base URL for the embedding API endpoint.
    """
    model: str
    api_key: str
    base_url: str

    def __init__(self, model_name: str, api_key: str, base_url: str) -> None:
        """Initialize the EmbedderClient with provider configuration.
        
        Args:
            model_name: Name of the embedding model to use (e.g., "text-embedding-3-small").
            api_key: API key for authenticating with the embedding service.
            base_url: Base URL for the embedding API endpoint.
        """
        self.model = model_name
        self.api_key = api_key
        self.base_url = base_url

    async def batch_embed(self, input: list) -> list:
        """Generate embeddings for a batch of input texts.
        
        Sends a batch embedding request to the configured API endpoint and
        handles various response formats. Supports OpenAI-compatible APIs
        and other providers with different response structures.
        
        Args:
            input: List of text strings to embed. Each string will be
                embedded into a vector representation.
        
        Returns:
            List of embedding dictionaries. Each dictionary contains an
            'embedding' key with the vector representation. Returns empty
            list if no embeddings were generated.
        
        Raises:
            ValueError: If the API returns a non-200 status code, an error
                response, or an unexpected response structure.
        """
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

            # Check HTTP status code
            if response.status != 200:
                error_text = await response.text()
                raise ValueError(f"Embedding API returned status {response.status}: {error_text}")

            data = await response.json()

            # Handle different response structures
            # OpenAI format: {"data": [{"embedding": [...]}, ...]}
            # Some APIs might return the data directly or in a different structure
            if isinstance(data, dict) and 'data' in data:
                embeddings = data['data']
            elif isinstance(data, list):
                # Response is already a list of embeddings
                embeddings = data
            elif isinstance(data, dict) and 'error' in data:
                # API returned an error
                error_info = data.get('error', {})
                error_msg = error_info.get('message', str(error_info)) if isinstance(error_info, dict) else str(error_info)
                raise ValueError(f"Embedding API error: {error_msg}")
            else:
                # Try to find embeddings in the response
                error_msg = f"Unexpected response structure: {list(data.keys()) if isinstance(data, dict) else type(data)}"
                raise ValueError(error_msg)

        return embeddings if embeddings else []

class ModelRegistry:
    """Registry for managing AI model instances from multiple providers.
    
    This class initializes and manages access to language models from various
    providers (OpenAI, Anthropic, Google/Gemini, OpenRouter) based on
    configuration settings. It also manages the embedding client for
    generating vector embeddings.
    
    Attributes:
        embedder_model: Embedding client instance, or None if not initialized.
    """
    embedder_model: EmbedderClient | None

    def __init__(self, config: Config):
        """Initialize the ModelRegistry with configuration.
        
        Reads model settings from the provided configuration and initializes
        model instances for all configured providers. Also sets up the
        embedding client based on the first available provider configuration.
        
        Args:
            config: Configuration object containing API keys and model settings
                for various providers.
        """
        self._models: Dict[str, AIModel] = {}
        self._initialize_models(config=config)

    def _initialize_models(self, config: Config):
        """Initialize model instances for all configured providers.
        
        Iterates through available model provider settings (OpenAI, Anthropic,
        Gemini, OpenRouter) and creates model instances for each configured
        provider. Also initializes the embedding client using the first
        available provider's configuration.
        
        Args:
            config: Configuration object containing model settings and API keys.
        """
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
            self._models['openrouter'] = OpenRouterModel(
                model_name=openrouter_settings.model_name,
                provider=OpenRouterProvider(
                    # base_url="https://openrouter.ai/api/v1",
                    api_key=openrouter_settings.api_key
                ),
            )
            self.embedder_model = EmbedderClient(
                model_name=config.embedding_model,
                api_key=config.open_router_key,
                base_url="https://openrouter.ai/api/v1/embeddings"
            )
        if models_settings.local:
            local_settings = models_settings.local
            self._models['local'] = OpenAIChatModel(
                model_name=local_settings.model_name,
                provider=OpenAIProvider(
                    base_url=local_settings.base_url,
                    api_key=local_settings.api_key
                ),
            )
            self.embedder_model = EmbedderClient(
                model_name=config.embedding_model,
                api_key=config.open_router_key,
                base_url="https://openrouter.ai/api/v1/embeddings"
            )
        
    def get_model(self, provider: str = 'openai') -> AIModel:
        """Retrieve a model instance for the specified provider.
        
        Args:
            provider: Name of the provider to retrieve. Must be one of:
                'openai', 'anthropic', 'gemini', or 'openrouter'.
                Defaults to 'openai'.
        
        Returns:
            AIModel instance for the requested provider.
        
        Raises:
            ValueError: If the provider is not supported, not configured,
                or no models have been initialized.
        """
        print(self._models)
        if provider not in self._models:
            raise ValueError(f"Model provider {provider} not supported.")
        elif not self._models:
            raise ValueError("No model was instantiated. Have you tried supplying an API key for the Model?")
        return self._models[provider]

    def get_embedder_model(self) -> EmbedderClient:
        """Retrieve the embedding client instance.
        
        Returns:
            EmbedderClient instance for generating embeddings.
        
        Raises:
            ValueError: If the embedder client was not initialized.
        """
        if self.embedder_model is None:
            raise ValueError(f"Embedder client could not be initialized: {self.embedder_model}")
        return self.embedder_model

    def list_configured_providers(self) -> list[str]:
        """Get a list of all configured model providers.
        
        Returns:
            List of provider names that have been successfully initialized
            (e.g., ['openai', 'anthropic']).
        """
        return list(self._models.keys())

    def has_any_model(self) -> bool:
        """Return True if at least one model provider is configured."""
        return len(self._models) > 0

    def get_all_models(self) -> Dict[str, AIModel]:
        """Get a dictionary of all initialized model instances.
        
        Returns a copy of the internal models dictionary, allowing access
        to all configured model providers without exposing the internal
        storage directly.
        
        Returns:
            Dictionary mapping provider names to their AIModel instances.
        """
        return self._models.copy()

