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

import docker

# Use centralized logger


from deadend_agent.core import init_rag_database, sandbox_setup, setup_model_registry, start_python_sandbox, stop_python_sandbox
from deadend_agent.config.settings import Config
from deadend_agent.models.registry import ModelRegistry
from deadend_agent.tools.browser_automation import PlaywrightRequester
from .rpc_models import (
    ComponentStatus,
    ComponentState,
    InitResult,
    HealthResult,
    AllHealthResult,
    AllInitResult,
)
from .init import (
    check_docker,
    check_pgvector_container,
    setup_pgvector_database,
    pull_sandboxed_kali_image,
    stop_pgvector_container,
)
from .logging import logger

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
        self.pgvector_state = ComponentState(name="pgvector")
        self.config_state = ComponentState(name="config")
        self.model_registry_state = ComponentState(name="model_registry")
        self.python_sandbox_state = ComponentState(name="python_sandbox")
        self.shell_sandbox_state = ComponentState(name="shell_sandbox")
        self.playwright_state = ComponentState(name="playwright")

        # Component instances
        self.config: Any = None
        self.model_registry: Any = None
        self.rag_connector: Any = None
        self.python_sandbox_process: Optional[subprocess.Popen] = None
        self.sandbox_manager: Any = None
        self.playwright_requester: Any = None

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
                raise RuntimeError("Docker daemon not available, Docker might needs to be installed")

            version_info = self.docker_client.version()
            self.docker_state.status = ComponentStatus.READY
            self.docker_state.metadata["version"] = version_info.get("Version", "unknown")
            self.docker_state.last_check = datetime.now()

            logger.debug(f"Docker initialized successfully, version: {version_info.get('Version', 'unknown')}")
            return InitResult(
                success=True,
                component="docker",
                status=ComponentStatus.READY,
                message="Docker daemon connected successfully",
                details={"version": version_info.get("Version", "unknown")},
            )
        except Exception as e:
            logger.error(f"Docker initialization failed: {e}")
            self.docker_state.status = ComponentStatus.ERROR
            self.docker_state.error_message = str(e)
            return InitResult(
                success=False,
                component="docker",
                status=ComponentStatus.ERROR,
                message=f"Docker initialization failed: {e}",
            )

    async def init_pgvector(self) -> InitResult:
        """Setup pgvector container and verify database connectivity."""
        logger.debug("Initializing pgvector component...")
        if self.docker_client is None:
            logger.error("Docker must be initialized before pgvector")
            return InitResult(
                success=False,
                component="pgvector",
                status=ComponentStatus.ERROR,
                message="Docker must be initialized first",
            )

        self.pgvector_state.status = ComponentStatus.INITIALIZING
        try:
            # Use existing init functions
            if not check_pgvector_container(self.docker_client):
                logger.debug("pgvector container not found, setting up...")
                if not setup_pgvector_database(self.docker_client):
                    raise RuntimeError("Failed to setup pgvector database")
                # Wait for async setup
                logger.debug("Waiting for pgvector container to be ready...")
                await asyncio.sleep(2)
            else:
                logger.debug("pgvector container already running")

            # Verify database connectivity using init_rag_database from core.py
            db_url = "postgresql://postgres:postgres@localhost:54320/codeindexerdb"
            logger.debug(f"Connecting to database: {db_url}")

            self.rag_connector = await init_rag_database(database_url=db_url)

            self.pgvector_state.status = ComponentStatus.READY
            self.pgvector_state.metadata["db_url"] = db_url
            self.pgvector_state.last_check = datetime.now()

            logger.debug("pgvector initialized successfully")
            return InitResult(
                success=True,
                component="pgvector",
                status=ComponentStatus.READY,
                message="pgvector database ready",
                details={"db_url": db_url},
            )
        except Exception as e:
            logger.error(f"pgvector initialization failed: {e}")
            self.pgvector_state.status = ComponentStatus.ERROR
            self.pgvector_state.error_message = str(e)
            return InitResult(
                success=False,
                component="pgvector",
                status=ComponentStatus.ERROR,
                message=f"pgvector initialization failed: {e}",
            )

    async def init_config(self) -> InitResult:
        """Load and validate configuration."""
        logger.debug("Initializing configuration...")
        self.config_state.status = ComponentStatus.INITIALIZING
        try:
            from deadend_agent import Config
            self.config = Config()
            self.config.configure()

            # Gather config summary
            has_openai = bool(getattr(self.config, "openai_api_key", None))
            has_anthropic = bool(getattr(self.config, "anthropic_api_key", None))
            has_gemini = bool(getattr(self.config, "gemini_api_key", None))

            providers = [p for p, v in [
                ("openai", has_openai),
                ("anthropic", has_anthropic),
                ("gemini", has_gemini),
            ] if v]

            self.config_state.status = ComponentStatus.READY
            self.config_state.metadata = {
                "has_openai": has_openai,
                "has_anthropic": has_anthropic,
                "has_gemini": has_gemini,
            }
            self.config_state.last_check = datetime.now()

            logger.debug(f"Configuration loaded, providers: {providers}")
            return InitResult(
                success=True,
                component="config",
                status=ComponentStatus.READY,
                message="Configuration loaded successfully",
                details={"providers_configured": providers},
            )
        except Exception as e:
            logger.error(f"Configuration loading failed: {e}")
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

            self.model_registry_state.status = ComponentStatus.READY
            self.model_registry_state.metadata["has_any_model"] = has_any
            self.model_registry_state.last_check = datetime.now()

            logger.debug(f"Model registry initialized, has_any_model: {has_any}")
            return InitResult(
                success=True,
                component="model_registry",
                status=ComponentStatus.READY,
                message="Model registry initialized successfully",
                details={"has_any_model": has_any},
            )
        except Exception as e:
            logger.error(f"Model registry initialization failed: {e}")
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

            logger.debug(f"Python sandbox started, PID: {self.python_sandbox_process.pid}")
            return InitResult(
                success=True,
                component="python_sandbox",
                status=ComponentStatus.READY,
                message="Python sandbox started",
                details={"pid": self.python_sandbox_process.pid, "port": 45555},
            )
        except Exception as e:
            logger.error(f"Python sandbox initialization failed: {e}")
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
            logger.error(f"Shell sandbox initialization failed: {e}")
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
            logger.error(f"Playwright initialization failed: {e}")
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
        1. Docker (required by pgvector and shell_sandbox)
        2. Config (required by model_registry)
        3. pgvector (requires Docker)
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

        # 3. pgvector - needs Docker
        logger.info("Step 3/7: Initializing pgvector database...")
        pgvector_result = await self.init_pgvector()
        results.append(pgvector_result)
        if not pgvector_result.success:
            failed.append("pgvector")
            logger.warning("pgvector initialization failed")

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
            logger.warning(f"Initialization completed with failures: {failed}")

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

    async def health_pgvector(self) -> HealthResult:
        """Check pgvector container and database connectivity."""
        start_time = time.time()
        try:
            if self.docker_client is None:
                return HealthResult(
                    component="pgvector",
                    healthy=False,
                    status=ComponentStatus.NOT_INITIALIZED,
                    message="Docker not initialized",
                )

            if not check_pgvector_container(self.docker_client):
                return HealthResult(
                    component="pgvector",
                    healthy=False,
                    status=ComponentStatus.UNHEALTHY,
                    message="Container not running",
                )

            # Check database connectivity
            if self.rag_connector:
                async with self.rag_connector.get_session() as session:
                    from sqlalchemy import text
                    await session.execute(text("SELECT 1"))

            latency = (time.time() - start_time) * 1000
            self.pgvector_state.last_check = datetime.now()

            return HealthResult(
                component="pgvector",
                healthy=True,
                status=ComponentStatus.READY,
                message="pgvector healthy",
                latency_ms=latency,
            )
        except Exception as e:
            self.pgvector_state.status = ComponentStatus.UNHEALTHY
            return HealthResult(
                component="pgvector",
                healthy=False,
                status=ComponentStatus.UNHEALTHY,
                message=f"pgvector health check failed: {e}",
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
            self.health_pgvector(),
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

    def get_model(self, provider: str = "openai"):
        """Get a model instance from the model registry.

        Args:
            provider: The LLM provider to use (openai, anthropic, gemini)

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
        return self.model_registry.get_model(provider=provider)

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

    def get_rag_connector(self):
        """Get the RAG database connector.

        Returns:
            RetrievalDatabaseConnector instance

        Raises:
            RuntimeError: If pgvector is not initialized
        """
        if self.rag_connector is None:
            raise RuntimeError(
                "RAG database not initialized. Call init_pgvector() first."
            )
        return self.rag_connector

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
        if self.rag_connector is None:
            missing.append("pgvector")
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

        # Optionally stop pgvector
        if self.docker_client:
            try:
                stop_pgvector_container(self.docker_client)
                results["pgvector"] = True
            except Exception:
                results["pgvector"] = False

        # Close RAG connector
        if self.rag_connector:
            try:
                if hasattr(self.rag_connector, "close"):
                    await self.rag_connector.close()
                results["rag_connector"] = True
            except Exception:
                results["rag_connector"] = False

        self._shutdown_event.set()
        return results


__all__ = ["ComponentManager"]
