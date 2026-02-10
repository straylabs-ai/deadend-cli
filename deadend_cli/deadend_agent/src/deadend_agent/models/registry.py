# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""AI model registry for managing model specifications and embedding clients.

This module provides a registry system for managing model *specifications*
(`ModelSpec` and `EmbeddingSpec`) and an embedding HTTP client. It no longer
depends on `pydantic_ai` model classes and instead exposes configuration
objects that are consumed by the CoreAgent and other components.
"""

from typing import Dict
import aiohttp
from litellm import aembedding, EmbeddingResponse
from pydantic import BaseModel
from deadend_agent.config.settings import Config, ModelSpec, EmbeddingSpec, ProvidersList
from deadend_agent.logging import logger

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
    api_key: str | None
    base_url: str | None
    vector_dim: int = 1536

    def __init__(self, model_name: str, api_key: str | None, base_url: str | None, vector_dim: int) -> None:
        """Initialize the EmbedderClient with provider configuration.
        
        Args:
            model_name: Name of the embedding model to use (e.g., "text-embedding-3-small").
            api_key: API key for authenticating with the embedding service.
            base_url: Base URL for the embedding API endpoint.
        """
        self.model = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.vector_dim = vector_dim

    async def batch_embed(self, input_texts: list[str]) -> list[dict]:
        """Generate embeddings for a batch of input texts.
        
        Sends a batch embedding request to the configured API endpoint and
        handles various response formats. Supports OpenAI-compatible APIs
        and other providers with different response structures.
        
        Args:
            input_texts: List of text strings to embed. Each string will be
                embedded into a vector representation.
        
        Returns:
            List of embedding dictionaries. Each dictionary contains an
            'embedding' key with the vector representation. Returns empty
            list if no embeddings were generated.
        
        Raises:
            ValueError: If the embedding call fails or returns an unexpected structure.
        """
        try:
            # Delegate embedding generation to LiteLLM's async embedding helper.
            #
            # NOTE:
            # - `self.model` should follow the LiteLLM model name convention,
            #   e.g. "openai/text-embedding-3-small" or "openrouter/qwen/qwen3-embedding-8b".
            # - API keys / base URLs are expected to be configured via LiteLLM
            #   environment variables or passed explicitly below.
            data = await aembedding(
                model=self.model,
                input=input_texts,
                api_base=self.base_url,
                api_key=self.api_key
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Embedding call via LiteLLM failed: %s", exc)
            raise ValueError(f"Embedding API error: {exc}") from exc

        # Handle different response structures
        # LiteLLM may return:
        # - A dict: {"data": [{"embedding": [...]}, ...]}
        # - A list: already a list of embeddings
        # - An EmbeddingResponse object: has a `.data` attribute
        if isinstance(data, dict) and "data" in data:
            embeddings = data["data"]
        elif isinstance(data, EmbeddingResponse):
            embeddings = data.data
        elif hasattr(data, "data"):
            # Newer LiteLLM returns an EmbeddingResponse object
            embeddings = getattr(data, "data")
        elif isinstance(data, list):
            # Response is already a list of embeddings
            embeddings = data
        elif isinstance(data, dict) and "error" in data:
            error_info = data.get("error", {})
            error_msg = (
                error_info.get("message", str(error_info))
                if isinstance(error_info, dict)
                else str(error_info)
            )
            raise ValueError(f"Embedding API error: {error_msg}")
        else:
            # Try to find embeddings in the response
            error_msg = (
                f"Unexpected embedding response structure: "
                f"{list(data.keys()) if isinstance(data, dict) else type(data)}"
            )
            raise ValueError(error_msg)

        return embeddings if embeddings else []

class ModelInfo(BaseModel):
    """Lightweight representation of a configured model.

    This is used by `ModelRegistry.get_all_models()` to expose a simplified
    view of all available models without leaking the full internal
    `ModelSpec` objects.
    """
    provider: str
    model_name: str
    type_model:  str | None = None

class ModelRegistry:
    """Registry for managing model specifications from multiple providers.
    
    This class initializes and manages access to language model specifications
    from various providers (OpenAI, Anthropic, Google/Gemini, OpenRouter, Local)
    based on configuration settings. It also manages the embedding client for
    generating vector embeddings via HTTP.
    
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
        # Map of provider name -> list[ModelSpec] (LLM models only, not embeddings)
        self._models: Dict[str, list[ModelSpec]] = {}
        # Keep a reference to config for runtime spec creation
        self._config = config
        self._initialize_models(config=config)

    def _initialize_models(self, config: Config):
        """Initialize model specifications and embedding client.
        
        Uses the TOML-backed `ProvidersList` populated via `Config.populate_providers()`
        as the single source of truth. Each entry is either a `ModelSpec` (LLM)
        or an `EmbeddingSpec` (embeddings)
        
        Args:
            config: Configuration object containing model settings and API keys.
        """
        self._models.clear()
        self.embedder_model = None

        providers_list: ProvidersList = config.all_model_providers()

        if providers_list and providers_list.model_providers:
            for spec in providers_list.model_providers:
                if isinstance(spec, EmbeddingSpec):
                    # Use the first embedding spec we encounter as the embedder client
                    if self.embedder_model is None:
                        # api_key, base_url = self._resolve_embedding_credentials(spec)
                        # LiteLLM expects model identifiers in the form "provider/model_name"
                        # e.g. "openai/text-embedding-3-small" or "openrouter/qwen/qwen3-embedding-8b".
                        self.embedder_model = EmbedderClient(
                            model_name=f"{spec.provider}/{spec.model_name}",
                            api_key=spec.api_key,
                            base_url=spec.base_url,
                            vector_dim=spec.vec_dim
                        )
                else:
                    # Regular language model spec - store all specs per provider.
                    if spec.provider not in self._models:
                        self._models[spec.provider] = []
                    self._models[spec.provider].append(spec)
        logger.info("models init: %s", str(self._models))

        # If no providers were found in TOML, registry will simply report no models.

    def _resolve_embedding_credentials(
        self,
        spec: EmbeddingSpec,
    ) -> tuple[str, str]:
        """Resolve API key and base URL for an embedding specification.

        Args:
            spec: Embedding specification from providers list.

        Returns:
            Tuple of (api_key, base_url).
        """
        # Use the values defined on the EmbeddingSpec itself. We do not apply
        # provider-based defaults here – the spec is the single source of truth.
        api_key = spec.api_key
        base_url = spec.base_url

        if not api_key or not base_url:
            raise ValueError(
                f"Embedding provider '{spec.provider}' is missing required credentials."
            )

        return api_key, base_url

    def get_model(self, provider: str = "openai", model_name: str | None = None) -> ModelSpec:
        """Retrieve a model specification.

        Args:
            provider: Preferred provider name when selecting by provider.
            model_name: Optional specific model name. If provided, the registry will
                return the `ModelSpec` whose ``model_name`` matches, regardless of
                provider. If omitted, the default spec for ``provider`` is returned.

        Returns:
            ModelSpec instance matching the requested provider or model name.

        Raises:
            ValueError: If no matching model is configured.
        """
        if not self._models:
            raise ValueError(
                "No model was instantiated. Have you tried supplying an API key for the Model?"
            )

        # If a specific model_name is requested, find the spec that has that name.
        if model_name is not None:
            return self._find_spec_by_model_name(model_name=model_name, selected_provider=provider)

        # Otherwise, return the first spec for the given provider (default).
        if provider not in self._models or not self._models[provider]:
            raise ValueError(f"Model provider {provider} not supported.")
        return self._models[provider][0]

    def _find_spec_by_model_name(
        self,
        model_name: str,
        selected_provider: str | None = None
    ) -> ModelSpec:
        """Locate an existing ModelSpec whose model_name matches.

        Args:
            model_name: The model name to search for.
            preferred_provider: Optional provider hint to prioritize when searching.

        Returns:
            The existing ModelSpec that has the requested model_name.

        Raises:
            ValueError: If no ModelSpec with that model_name is configured.
        """
        # 1) Prefer a match within the in-memory map, honoring preferred_provider first
        if selected_provider and selected_provider in self._models:
            for spec in self._models[selected_provider]:
                if spec.model_name == model_name:
                    return spec

        for specs in self._models.values():
            for spec in specs:
                if spec.model_name == model_name:
                    return spec

        # 2) Fallback: search the full providers list from config (ModelSpec only)
        providers_list = self._config.all_model_providers()
        for spec in providers_list.model_providers:
            if isinstance(spec, ModelSpec) and not isinstance(spec, EmbeddingSpec):
                if spec.model_name == model_name:
                    return spec

        raise ValueError(f"No model configured with name '{model_name}'")

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

    def get_all_models(self) -> Dict[str, list[ModelInfo]]:
        """Get a dictionary of all initialized model specifications.
        
        Returns a copy of the internal models dictionary, allowing access
        to all configured model providers and their associated model specs
        without exposing the internal storage directly.
        
        Returns:
            Dictionary mapping provider names to lists of their ModelSpec instances.
        """
        all_models: Dict[str, list[ModelInfo]] = {}

        for provider, model_specs in self._models.items():
            provider_models = [ModelInfo(
                provider=spec.provider,
                model_name=spec.model_name,
                type_model=None) for spec in model_specs]
            all_models[provider] = provider_models

        return all_models
    
    def add_model_provider(
        self,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        type_model: str | None = None,
        vec_dim: int | None = None
    ):
        """Add a new model provider to the configuration and reinitialize the registry.
        
        Args:
            provider: Provider name (e.g., "openai", "anthropic")
            model_name: Model name
            api_key: API key (optional)
            base_url: Base URL (optional)
            type_model: Type of model, "embeddings" for embedding models (optional)
            vec_dim: Vector dimension for embedding models (optional)
        """
        self._config.add_provider(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            type_model=type_model,
            vec_dim=vec_dim
        )
        # Reinitialize models to reflect the new provider
        self._initialize_models(config=self._config)

    def update_model_by_provider(
        self,
        selected_provider: str,
        selected_model: str,
        new_provider: str,
        new_model: str,
        api_key: str | None
    ):
        """Update an existing model configuration and refresh the registry.

        This looks up an existing `ModelSpec` by its current provider/model
        pair, applies the requested changes through the underlying `Config`,
        and then leaves the registry ready to be re-initialized or queried
        with the updated settings.

        Args:
            selected_provider: Current provider name of the model to update.
            selected_model: Current model name to identify the spec.
            new_provider: New provider name to set on the model.
            new_model: New model name to set on the model.
            api_key: Optional new API key for the updated model.
        """
        selected_model_spec = self._find_spec_by_model_name(
            model_name=selected_model,
            selected_provider=selected_provider
        )

        self._config.update_provider(
            updated_provider=selected_model_spec,
            provider=new_provider,
            model_name=new_model,
            api_key=api_key,
            type_model=None,
            vec_dim=None
        )
