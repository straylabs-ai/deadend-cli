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
from docker.errors import DockerException, NotFound

from .rpc_models import (
    ComponentStatus,
    ComponentState,
    InitResult,
    HealthResult,
    AllHealthResult,
)
from .init import (
    check_docker,
    check_pgvector_container,
    setup_pgvector_database,
    pull_sandboxed_kali_image,
    stop_pgvector_container,
)


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
        self.python_sandbox_state = ComponentState(name="python_sandbox")
        self.shell_sandbox_state = ComponentState(name="shell_sandbox")
        self.playwright_state = ComponentState(name="playwright")

        # Component instances
        self.config: Any = None
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
        self.docker_state.status = ComponentStatus.INITIALIZING
        try:
            self.docker_client = docker.from_env()

            if not check_docker(self.docker_client):
                raise RuntimeError("Docker daemon not available")

            version_info = self.docker_client.version()
            self.docker_state.status = ComponentStatus.READY
            self.docker_state.metadata["version"] = version_info.get("Version", "unknown")
            self.docker_state.last_check = datetime.now()

            return InitResult(
                success=True,
                component="docker",
                status=ComponentStatus.READY,
                message="Docker daemon connected successfully",
                details={"version": version_info.get("Version", "unknown")},
            )
        except Exception as e:
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
        if self.docker_client is None:
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
                if not setup_pgvector_database(self.docker_client):
                    raise RuntimeError("Failed to setup pgvector database")
                # Wait for async setup
                await asyncio.sleep(2)

            # Verify database connectivity
            db_url = "postgresql://postgres:postgres@localhost:54320/codeindexerdb"

            from deadend_agent.rag.db_cruds import RetrievalDatabaseConnector

            self.rag_connector = RetrievalDatabaseConnector(database_url=db_url)
            await self.rag_connector.initialize_database()

            self.pgvector_state.status = ComponentStatus.READY
            self.pgvector_state.metadata["db_url"] = db_url
            self.pgvector_state.last_check = datetime.now()

            return InitResult(
                success=True,
                component="pgvector",
                status=ComponentStatus.READY,
                message="pgvector database ready",
                details={"db_url": db_url},
            )
        except Exception as e:
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

            return InitResult(
                success=True,
                component="config",
                status=ComponentStatus.READY,
                message="Configuration loaded successfully",
                details={"providers_configured": providers},
            )
        except Exception as e:
            self.config_state.status = ComponentStatus.ERROR
            self.config_state.error_message = str(e)
            return InitResult(
                success=False,
                component="config",
                status=ComponentStatus.ERROR,
                message=f"Configuration loading failed: {e}",
            )

    async def init_python_sandbox(self) -> InitResult:
        """Download (if needed) and start Python sandbox."""
        self.python_sandbox_state.status = ComponentStatus.INITIALIZING
        try:
            from deadend_agent.core import download_python_sandbox, start_python_sandbox

            download_python_sandbox()
            self.python_sandbox_process = start_python_sandbox()

            await asyncio.sleep(1)
            if self.python_sandbox_process.poll() is not None:
                raise RuntimeError("Python sandbox process terminated unexpectedly")

            self.python_sandbox_state.status = ComponentStatus.READY
            self.python_sandbox_state.metadata["pid"] = self.python_sandbox_process.pid
            self.python_sandbox_state.metadata["port"] = 45555
            self.python_sandbox_state.last_check = datetime.now()

            return InitResult(
                success=True,
                component="python_sandbox",
                status=ComponentStatus.READY,
                message="Python sandbox started",
                details={"pid": self.python_sandbox_process.pid, "port": 45555},
            )
        except Exception as e:
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
        if self.docker_client is None:
            return InitResult(
                success=False,
                component="shell_sandbox",
                status=ComponentStatus.ERROR,
                message="Docker must be initialized first",
            )

        self.shell_sandbox_state.status = ComponentStatus.INITIALIZING
        try:
            # Use existing init function
            pull_sandboxed_kali_image(self.docker_client)

            from deadend_agent.sandbox.sandbox_manager import SandboxManager
            self.sandbox_manager = SandboxManager()

            self.shell_sandbox_state.status = ComponentStatus.READY
            self.shell_sandbox_state.metadata["image"] = "xoxruns/sandboxed_kali"
            self.shell_sandbox_state.last_check = datetime.now()

            return InitResult(
                success=True,
                component="shell_sandbox",
                status=ComponentStatus.READY,
                message="Shell sandbox ready (Kali image available)",
                details={"image": "xoxruns/sandboxed_kali"},
            )
        except Exception as e:
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
        self.playwright_state.status = ComponentStatus.INITIALIZING
        try:
            from deadend_agent.tools.browser_automation.pw_requester import PlaywrightRequester

            self.playwright_requester = PlaywrightRequester(
                verify_ssl=False,
                session_id="daemon_session",
            )
            await self.playwright_requester._initialize()

            self.playwright_state.status = ComponentStatus.READY
            self.playwright_state.metadata["browser"] = "chromium"
            self.playwright_state.metadata["headless"] = True
            self.playwright_state.last_check = datetime.now()

            return InitResult(
                success=True,
                component="playwright",
                status=ComponentStatus.READY,
                message="Playwright browser initialized",
                details={"browser": "chromium", "headless": True},
            )
        except Exception as e:
            self.playwright_state.status = ComponentStatus.ERROR
            self.playwright_state.error_message = str(e)
            return InitResult(
                success=False,
                component="playwright",
                status=ComponentStatus.ERROR,
                message=f"Playwright initialization failed: {e}",
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

        components = []
        for r in results:
            if isinstance(r, Exception):
                components.append(HealthResult(
                    component="unknown",
                    healthy=False,
                    status=ComponentStatus.ERROR,
                    message=str(r),
                ))
            else:
                components.append(r)

        return AllHealthResult(
            overall_healthy=all(c.healthy for c in components),
            components=components,
        )

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
                self.python_sandbox_process.terminate()
                try:
                    self.python_sandbox_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.python_sandbox_process.kill()
                    self.python_sandbox_process.wait()
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
