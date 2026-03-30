# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Component manager for initializing and managing daemon components."""
from __future__ import annotations
import asyncio
import subprocess
import time
from datetime import datetime
from typing import Any, Optional
from deadend_agent import ModelRegistry
import docker
from deadend_agent.core import (
    init_rag_session_manager,
    sandbox_setup,
    setup_model_registry,
    start_python_sandbox,
    stop_python_sandbox,
    Config,
)
from deadend_agent.rag.session_manager import RagSessionManager
from deadend_agent.tools.browser_automation import PlaywrightRequester
from .jsonrpc.rpc_models import (
    ComponentStatus,
    ComponentState,
    InitResult,
    HealthResult,
    AllHealthResult,
    AllInitResult,
)
from .init import (
    check_docker,
    pull_sandboxed_kali_image,
)
from .cli_logging import logger

class ComponentManager:
    """Manages lifecycle of all daemon components.

    Reuses existing init functions and wraps them with state tracking
    and health check capabilities for the RPC server.
    """

    def __init__(self):
        # Docker client
        self.docker_client: Optional[docker.DockerClient] = None

        # Component states
        self.docker_state = ComponentState(name="docker")
        self.rag_state = ComponentState(name="rag")
        self.config_state = ComponentState(name="config")
        self.model_registry_state = ComponentState(name="model_registry")
        self.python_sandbox_state = ComponentState(name="python_sandbox")
        self.shell_sandbox_state = ComponentState(name="shell_sandbox")
        self.playwright_state = ComponentState(name="playwright")

        # Component instances
        self.config: Config | None = None
        self.model_registry: ModelRegistry = None
        self.rag_session_manager: RagSessionManager | None = None
        self.python_sandbox_process: Optional[subprocess.Popen] = None
        self.sandbox_manager: Any = None
        self.playwright_requester: Any = None

        # Current LLM provider (defaults to first available or "openai")
        self.current_llm_provider: str = "openai"

        # Shutdown event
        self._shutdown_event = asyncio.Event()

    # ==========================================================================
    # Initialization Methods
    # ==========================================================================

    async def init_docker(self) -> InitResult:
        """Initialize Docker client and verify daemon connectivity."""
        logger.debug("Initializing Docker component...")
        self.docker_state.status = ComponentStatus.INITIALIZING
        try:
            # Checking if docker is available
            logger.debug("Creating Docker client from environment")
            self.docker_client = docker.from_env()

            if not check_docker(self.docker_client):
                raise RuntimeError(
                    "Docker daemon not available, \
                    Please install Docker from: https://docs.docker.com/get-docker/"
                )

            version_info = self.docker_client.version()
            self.docker_state.status = ComponentStatus.READY
            self.docker_state.metadata["version"] = version_info.get("Version", "unknown")
            self.docker_state.last_check = datetime.now()

            logger.debug(
                "Docker initialized successfully, version: %s", 
                version_info.get('Version', 'unknown')
            )
            return InitResult(
                success=True,
                component="docker",
                status=ComponentStatus.READY,
                message="Docker daemon connected successfully",
                details={"version": version_info.get("Version", "unknown")},
            )
        except Exception as e:
            logger.error("Docker initialization failed: %s", e)
            self.docker_state.status = ComponentStatus.ERROR
            self.docker_state.error_message = str(e)
            return InitResult(
                success=False,
                component="docker",
                status=ComponentStatus.ERROR,
                message=f"Docker initialization failed: {e}",
            )

    async def init_rag(self) -> InitResult:
        """Initialize the SQLite-based RAG session manager.

        No Docker dependency — creates the storage directory and returns
        immediately.
        """
        logger.debug("Initializing RAG session manager...")
        self.rag_state.status = ComponentStatus.INITIALIZING
        try:
            storage_root = self.config.agents_storage_root if self.config else None
            self.rag_session_manager = init_rag_session_manager(
                storage_root=storage_root
            )

            self.rag_state.status = ComponentStatus.READY
            self.rag_state.metadata["storage_root"] = str(
                self.rag_session_manager._root
            )
            self.rag_state.last_check = datetime.now()

            logger.debug("RAG session manager initialized at %s", self.rag_session_manager._root)
            return InitResult(
                success=True,
                component="rag",
                status=ComponentStatus.READY,
                message="RAG session manager ready (SQLite)",
                details={"storage_root": str(self.rag_session_manager._root)},
            )
        except Exception as e:
            logger.error("RAG initialization failed: %s", e)
            self.rag_state.status = ComponentStatus.ERROR
            self.rag_state.error_message = str(e)
            return InitResult(
                success=False,
                component="rag",
                status=ComponentStatus.ERROR,
                message=f"RAG initialization failed: {e}",
            )

    async def init_config(self) -> InitResult:
        """Load and validate configuration."""
        logger.debug("Initializing configuration...")
        self.config_state.status = ComponentStatus.INITIALIZING
        try:
            from deadend_agent import Config
            self.config = Config()
            self.config.configure()
            self.config.populate_providers()
            self.config_state.status = ComponentStatus.READY
            self.config_state.last_check = datetime.now()

            logger.debug("Configuration loaded, providers: %s", self.config.providers.model_dump())
            return InitResult(
                success=True,
                component="config",
                status=ComponentStatus.READY,
                message="Configuration loaded successfully",
                details={"providers_configured": str(self.config.providers.model_dump())},
            )
        except Exception as e:
            logger.error("Configuration loading failed: %s", e)
            self.config_state.status = ComponentStatus.ERROR
            self.config_state.error_message = str(e)
            return InitResult(
                success=False,
                component="config",
                status=ComponentStatus.ERROR,
                message=f"Configuration loading failed: {e}",
            )

    async def init_model_registry(self) -> InitResult:
        """Initialize model registry using config."""
        logger.debug("Initializing model registry...")
        if self.config is None:
            logger.error("Config must be initialized before model registry")
            return InitResult(
                success=False,
                component="model_registry",
                status=ComponentStatus.ERROR,
                message="Config must be initialized first",
            )

        self.model_registry_state.status = ComponentStatus.INITIALIZING
        try:
            self.model_registry = setup_model_registry(self.config)

            # Check which models are available
            has_any = self.model_registry.has_any_model()
            
            # Set default provider to first available, or keep current if available
            if has_any:
                available = self.model_registry.list_configured_providers()
                if available:
                    # If current provider is not available, switch to first available
                    if self.current_llm_provider not in available:
                        self.current_llm_provider = available[0]
                        logger.info("Defaulting to first available provider: %s", self.current_llm_provider)

            self.model_registry_state.status = ComponentStatus.READY
            self.model_registry_state.metadata["has_any_model"] = has_any
            self.model_registry_state.last_check = datetime.now()

            logger.debug("Model registry initialized, has_any_model: %s, current_provider: %s", has_any, self.current_llm_provider)
            return InitResult(
                success=True,
                component="model_registry",
                status=ComponentStatus.READY,
                message="Model registry initialized successfully",
                details={"has_any_model": has_any},
            )
        except Exception as e:
            logger.error("Model registry initialization failed: %s", e)
            self.model_registry_state.status = ComponentStatus.ERROR
            self.model_registry_state.error_message = str(e)
            return InitResult(
                success=False,
                component="model_registry",
                status=ComponentStatus.ERROR,
                message=f"Model registry initialization failed: {e}",
            )

    async def init_python_sandbox(self) -> InitResult:
        """Download (if needed) and start Python sandbox."""
        logger.debug("Initializing Python sandbox...")
        self.python_sandbox_state.status = ComponentStatus.INITIALIZING
        try:
            logger.debug("Starting Python sandbox process...")
            self.python_sandbox_process = start_python_sandbox()

            await asyncio.sleep(1)
            if self.python_sandbox_process.poll() is not None:
                raise RuntimeError("Python sandbox process terminated unexpectedly")

            self.python_sandbox_state.status = ComponentStatus.READY
            self.python_sandbox_state.metadata["pid"] = self.python_sandbox_process.pid
            self.python_sandbox_state.metadata["port"] = 45555
            self.python_sandbox_state.last_check = datetime.now()

            logger.debug("Python sandbox started, PID: %s", self.python_sandbox_process.pid)
            return InitResult(
                success=True,
                component="python_sandbox",
                status=ComponentStatus.READY,
                message="Python sandbox started",
                details={"pid": self.python_sandbox_process.pid, "port": 45555},
            )
        except Exception as e:
            logger.error("Python sandbox initialization failed: %s", e)
            self.python_sandbox_state.status = ComponentStatus.ERROR
            self.python_sandbox_state.error_message = str(e)
            return InitResult(
                success=False,
                component="python_sandbox",
                status=ComponentStatus.ERROR,
                message=f"Python sandbox initialization failed: {e}",
            )

    async def init_shell_sandbox(self) -> InitResult:
        """Pull Kali image and prepare shell sandbox."""
        logger.debug("Initializing shell sandbox...")
        if self.docker_client is None:
            logger.error("Docker must be initialized before shell sandbox")
            return InitResult(
                success=False,
                component="shell_sandbox",
                status=ComponentStatus.ERROR,
                message="Docker must be initialized first",
            )

        self.shell_sandbox_state.status = ComponentStatus.INITIALIZING
        try:
            # Use existing init function
            logger.debug("Pulling Kali sandbox image...")
            pull_sandboxed_kali_image(self.docker_client)
            logger.debug("Creating SandboxManager...")
            self.sandbox_manager = sandbox_setup()

            self.shell_sandbox_state.status = ComponentStatus.READY
            self.shell_sandbox_state.metadata["image"] = "xoxruns/sandboxed_kali"
            self.shell_sandbox_state.last_check = datetime.now()

            logger.debug("Shell sandbox initialized successfully")
            return InitResult(
                success=True,
                component="shell_sandbox",
                status=ComponentStatus.READY,
                message="Shell sandbox ready (Kali image available)",
                details={"image": "xoxruns/sandboxed_kali"},
            )
        except Exception as e:
            logger.error("Shell sandbox initialization failed: %s", e)
            self.shell_sandbox_state.status = ComponentStatus.ERROR
            self.shell_sandbox_state.error_message = str(e)
            return InitResult(
                success=False,
                component="shell_sandbox",
                status=ComponentStatus.ERROR,
                message=f"Shell sandbox initialization failed: {e}",
            )

    async def init_playwright(self) -> InitResult:
        """Initialize Playwright browser."""
        logger.debug("Initializing Playwright browser...")
        self.playwright_state.status = ComponentStatus.INITIALIZING
        try:
            logger.debug("Creating PlaywrightRequester...")
            self.playwright_requester = PlaywrightRequester(
                verify_ssl=False,
                session_id="daemon_session",
            )
            await self.playwright_requester._initialize()

            self.playwright_state.status = ComponentStatus.READY
            self.playwright_state.metadata["browser"] = "chromium"
            self.playwright_state.metadata["headless"] = True
            self.playwright_state.last_check = datetime.now()

            logger.debug("Playwright browser initialized successfully")
            return InitResult(
                success=True,
                component="playwright",
                status=ComponentStatus.READY,
                message="Playwright browser initialized",
                details={"browser": "chromium", "headless": True},
            )
        except Exception as e:
            logger.error("Playwright initialization failed: %s", e)
            self.playwright_state.status = ComponentStatus.ERROR
            self.playwright_state.error_message = str(e)
            return InitResult(
                success=False,
                component="playwright",
                status=ComponentStatus.ERROR,
                message=f"Playwright initialization failed: {e}",
            )

    async def init_all(self) -> AllInitResult:
        """Initialize all components in the correct order.

        Initialization order:
        1. Docker (required by shell_sandbox)
        2. Config (required by model_registry and RAG)
        3. RAG session manager (requires Config, SQLite-based — no Docker)
        4. model_registry (requires Config)
        5. python_sandbox (standalone)
        6. shell_sandbox (requires Docker)
        7. playwright (standalone)

        Returns:
            AllInitResult with overall success status and individual component results.
        """
        logger.info("Starting initialization of all components...")
        results: list[InitResult] = []
        failed: list[str] = []

        # 1. Docker - foundation for containers
        logger.info("Step 1/7: Initializing Docker...")
        docker_result = await self.init_docker()
        results.append(docker_result)
        if not docker_result.success:
            failed.append("docker")
            logger.warning("Docker initialization failed, some components may not work")

        # 2. Config - needed for model registry
        logger.info("Step 2/7: Loading configuration...")
        config_result = await self.init_config()
        results.append(config_result)
        if not config_result.success:
            failed.append("config")
            logger.warning("Config loading failed")

        # 3. RAG (SQLite session manager — no Docker needed)
        logger.info("Step 3/7: Initializing RAG session manager...")
        rag_result = await self.init_rag()
        results.append(rag_result)
        if not rag_result.success:
            failed.append("rag")
            logger.warning("RAG initialization failed")

        # 4. Model registry - needs Config
        logger.info("Step 4/7: Initializing model registry...")
        model_registry_result = await self.init_model_registry()
        results.append(model_registry_result)
        if not model_registry_result.success:
            failed.append("model_registry")
            logger.warning("Model registry initialization failed")

        # 5. Python sandbox - standalone
        logger.info("Step 5/7: Starting Python sandbox...")
        python_sandbox_result = await self.init_python_sandbox()
        results.append(python_sandbox_result)
        if not python_sandbox_result.success:
            failed.append("python_sandbox")
            logger.warning("Python sandbox initialization failed")

        # 6. Shell sandbox - needs Docker
        logger.info("Step 6/7: Preparing shell sandbox...")
        shell_sandbox_result = await self.init_shell_sandbox()
        results.append(shell_sandbox_result)
        if not shell_sandbox_result.success:
            failed.append("shell_sandbox")
            logger.warning("Shell sandbox initialization failed")

        # 7. Playwright - standalone
        logger.info("Step 7/7: Initializing Playwright browser...")
        playwright_result = await self.init_playwright()
        results.append(playwright_result)
        if not playwright_result.success:
            failed.append("playwright")
            logger.warning("Playwright initialization failed")

        overall_success = len(failed) == 0
        if overall_success:
            logger.info("All components initialized successfully")
        else:
            logger.warning("Initialization completed with failures: %s", failed)

        return AllInitResult(
            overall_success=overall_success,
            components=results,
            failed_components=failed,
        )

    # ==========================================================================
    # Health Check Methods
    # ==========================================================================

    async def health_docker(self) -> HealthResult:
        """Check Docker daemon health."""
        start_time = time.time()
        try:
            if self.docker_client is None:
                return HealthResult(
                    component="docker",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="Docker client not initialized",
                )

            self.docker_client.ping()
            latency = (time.time() - start_time) * 1000
            self.docker_state.last_check = datetime.now()

            return HealthResult(
                component="docker",
                healthy=True,
                status=ComponentStatus.READY,
                message="Docker daemon responsive",
                latency_ms=latency,
            )
        except Exception as e:
            self.docker_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="docker",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"Docker health check failed: {e}",
            )

    async def health_rag(self) -> HealthResult:
        """Check RAG session manager health."""
        start_time = time.time()
        try:
            if self.rag_session_manager is None:
                return HealthResult(
                    component="rag",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="RAG session manager not initialized",
                )

            latency = (time.time() - start_time) * 1000
            self.rag_state.last_check = datetime.now()

            return HealthResult(
                component="rag",
                healthy=True,
                status=ComponentStatus.READY,
                message="RAG session manager healthy",
                latency_ms=latency,
            )
        except Exception as e:
            self.rag_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="rag",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"RAG health check failed: {e}",
            )

    async def health_python_sandbox(self) -> HealthResult:
        """Check Python sandbox process health."""
        start_time = time.time()
        try:
            if self.python_sandbox_process is None:
                return HealthResult(
                    component="python_sandbox",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="Python sandbox not started",
                )

            if self.python_sandbox_process.poll() is not None:
                self.python_sandbox_state.status = ComponentStatus.STOPPED
                return HealthResult(
                    component="python_sandbox",
                    healthy=False,
                    status=ComponentStatus.STOPPED,
                    message=f"Process exited with code {self.python_sandbox_process.returncode}",
                )

            latency = (time.time() - start_time) * 1000
            self.python_sandbox_state.last_check = datetime.now()

            return HealthResult(
                component="python_sandbox",
                healthy=True,
                status=ComponentStatus.READY,
                message="Python sandbox healthy",
                latency_ms=latency,
                details={"pid": self.python_sandbox_process.pid},
            )
        except Exception as e:
            self.python_sandbox_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="python_sandbox",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"Python sandbox health check failed: {e}",
            )

    async def health_shell_sandbox(self) -> HealthResult:
        """Check shell sandbox readiness."""
        start_time = time.time()
        try:
            if self.sandbox_manager is None:
                return HealthResult(
                    component="shell_sandbox",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="Sandbox manager not initialized",
                )

            if self.docker_client:
                self.docker_client.images.get("xoxruns/sandboxed_kali")

            latency = (time.time() - start_time) * 1000
            self.shell_sandbox_state.last_check = datetime.now()

            return HealthResult(
                component="shell_sandbox",
                healthy=True,
                status=ComponentStatus.READY,
                message="Shell sandbox ready",
                latency_ms=latency,
            )
        except Exception as e:
            self.shell_sandbox_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="shell_sandbox",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"Shell sandbox health check failed: {e}",
            )

    async def health_playwright(self) -> HealthResult:
        """Check Playwright browser health."""
        start_time = time.time()
        try:
            if self.playwright_requester is None:
                return HealthResult(
                    component="playwright",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="Playwright not initialized",
                )

            if hasattr(self.playwright_requester, "browser") and self.playwright_requester.browser:
                if self.playwright_requester.browser.is_connected():
                    latency = (time.time() - start_time) * 1000
                    self.playwright_state.last_check = datetime.now()
                    return HealthResult(
                        component="playwright",
                        healthy=True,
                        status=ComponentStatus.READY,
                        message="Playwright browser connected",
                        latency_ms=latency,
                    )

            return HealthResult(
                component="playwright",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message="Browser not connected",
            )
        except Exception as e:
            self.playwright_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="playwright",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"Playwright health check failed: {e}",
            )

    async def health_all(self) -> AllHealthResult:
        """Run all health checks concurrently."""
        results = await asyncio.gather(
            self.health_docker(),
            self.health_rag(),
            self.health_python_sandbox(),
            self.health_shell_sandbox(),
            self.health_playwright(),
            return_exceptions=True,
        )

        components: list[HealthResult] = []
        for result in results:
            if isinstance(result, Exception):
                components.append(HealthResult(
                    component="unknown",
                    healthy=False,
                    status=ComponentStatus.ERROR,
                    message=str(result),
                ))
            else:
                components.append(result)

        return AllHealthResult(
            overall_healthy=all(component.healthy for component in components),
            components=components,
        )
    # ==========================================================================
    # Component Access Methods
    # ==========================================================================

    def get_model(self, provider: str | None = None, model_name: str | None = None):
        """Get a model instance from the model registry.

        Args:
            provider: The LLM provider to use (openai, anthropic, gemini, openrouter, local).
                     If None, uses the current_llm_provider.
            model_name: Optional model name override. If provided, creates a model
                       instance with this specific model name.

        Returns:
            Model instance

        Raises:
            RuntimeError: If model registry is not initialized or no models available
        """
        if self.model_registry is None:
            raise RuntimeError(
                "Model registry not initialized. Call init_model_registry() first."
            )

        if not self.model_registry.has_any_model():
            raise RuntimeError(
                "No LLM model configured. Run `deadend init` to initialize the model configuration."
            )

        # Use current provider if not specified
        if provider is None:
            provider = self.current_llm_provider
        return self.model_registry.get_model(provider=provider, model_name=model_name)

    def set_llm_provider(self, provider: str) -> None:
        """Set the current LLM provider.

        Args:
            provider: The provider name (openai, anthropic, gemini, openrouter, local)

        Raises:
            ValueError: If provider is not configured or not available
        """
        if self.model_registry is None:
            raise RuntimeError(
                "Model registry not initialized. Call init_model_registry() first."
            )
        
        # Check if provider is available
        available_providers = self.model_registry.list_configured_providers()
        if provider not in available_providers:
            raise ValueError(
                f"Provider '{provider}' is not configured. "
                f"Available providers: {', '.join(available_providers)}"
            )
        
        self.current_llm_provider = provider
        logger.info("LLM provider set to: %s", provider)

    def get_llm_provider(self) -> str:
        """Get the current LLM provider.

        Returns:
            Current provider name
        """
        return self.current_llm_provider

    def get_all_models(self) -> dict[str, Any]:
        """List all available LLM providers and their configuration status.

        Returns:
            Dictionary with 'current' provider and 'providers' list containing
            provider info (name, configured status, model name)
        """
        if self.model_registry is None:
            return {
                "current": self.current_llm_provider,
                "providers": []
            }
        return self.model_registry.get_all_models()

    def add_model_provider(
        self,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        type_model: str | None = None,
        vec_dim: int | None = None
    ) -> None:
        """Add a new model provider to the configuration.

        Args:
            provider: Provider name (e.g., "openai", "anthropic")
            model_name: Model name
            api_key: API key (optional)
            base_url: Base URL (optional)
            type_model: Type of model, "embeddings" for embedding models (optional)
            vec_dim: Vector dimension for embedding models (optional)

        Raises:
            RuntimeError: If model registry is not initialized
        """
        if self.model_registry is None:
            raise RuntimeError(
                "Model registry not initialized. Call init_model_registry() first."
            )
        
        self.model_registry.add_model_provider(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            type_model=type_model,
            vec_dim=vec_dim
        )
        
        # Update current provider if it's a regular model and no provider is set yet
        if type_model != "embeddings":
            available_providers = self.model_registry.list_configured_providers()
            if available_providers and self.current_llm_provider not in available_providers:
                self.current_llm_provider = available_providers[0]
                logger.info("Defaulting to first available provider: %s", self.current_llm_provider)

    def get_embedder(self):
        """Get the embedder model from the model registry.

        Returns:
            Embedder model instance

        Raises:
            RuntimeError: If model registry is not initialized
        """
        if self.model_registry is None:
            raise RuntimeError(
                "Model registry not initialized. Call init_model_registry() first."
            )
        return self.model_registry.get_embedder_model()

    def get_rag_session_manager(self) -> RagSessionManager:
        """Get the RAG session manager.

        Returns:
            RagSessionManager instance

        Raises:
            RuntimeError: If RAG is not initialized
        """
        if self.rag_session_manager is None:
            raise RuntimeError(
                "RAG session manager not initialized. Call init_rag() first."
            )
        return self.rag_session_manager

    def create_task_sandbox(self, network_name: str = "host"):
        """Create a new sandbox for a task.

        Args:
            network_name: Docker network to use for the sandbox

        Returns:
            Sandbox instance

        Raises:
            RuntimeError: If sandbox manager is not initialized
        """
        if self.sandbox_manager is None:
            raise RuntimeError(
                "Sandbox manager not initialized. Call init_shell_sandbox() first."
            )
        sandbox_id = self.sandbox_manager.create_sandbox(
            "xoxruns/sandboxed_kali", network_name=network_name
        )
        return self.sandbox_manager.get_sandbox(sandbox_id=sandbox_id)

    def is_ready_for_tasks(self) -> tuple[bool, list[str]]:
        """Check if all required components are initialized for running tasks.

        Returns:
            Tuple of (is_ready, list of missing components)
        """
        missing = []
        if self.config is None:
            missing.append("config")
        if self.model_registry is None:
            missing.append("model_registry")
        if self.rag_session_manager is None:
            missing.append("rag")
        if self.sandbox_manager is None:
            missing.append("shell_sandbox")
        return (len(missing) == 0, missing)

    # ==========================================================================
    # Shutdown
    # ==========================================================================

    async def shutdown(self) -> dict[str, bool]:
        """Gracefully stop all components."""
        results: dict[str, bool] = {}

        # Stop Playwright
        if self.playwright_requester:
            try:
                if hasattr(self.playwright_requester, "_cleanup"):
                    await self.playwright_requester._cleanup()
                self.playwright_state.status = ComponentStatus.STOPPED
                results["playwright"] = True
            except Exception:
                results["playwright"] = False

        # Stop Python sandbox
        if self.python_sandbox_process and self.python_sandbox_process.poll() is None:
            try:
                stop_python_sandbox(process=self.python_sandbox_process)
                self.python_sandbox_state.status = ComponentStatus.STOPPED
                results["python_sandbox"] = True
            except Exception:
                results["python_sandbox"] = False

        # Stop shell sandboxes
        if self.sandbox_manager:
            try:
                if hasattr(self.sandbox_manager, "stop_all"):
                    self.sandbox_manager.stop_all()
                self.shell_sandbox_state.status = ComponentStatus.STOPPED
                results["shell_sandbox"] = True
            except Exception:
                results["shell_sandbox"] = False

        # Close RAG session manager
        if self.rag_session_manager:
            try:
                await self.rag_session_manager.close_all()
                results["rag"] = True
            except Exception:
                results["rag"] = False

        self._shutdown_event.set()
        return results


__all__ = ["ComponentManager"]
