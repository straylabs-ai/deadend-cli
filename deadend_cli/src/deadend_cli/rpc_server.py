# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""JSON-RPC server over stdio for communicating with other front-end components.

This server supports:
- Component initialization (Docker, pgvector, config, sandboxes, Playwright)
- Health checks for all components
- Event streaming for agent/tool execution
- Approval workflow for dangerous tool calls
- Workflow interruption
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Coroutine, Dict, Optional

from deadend_agent import (
    Config,
    DeadEndAgent,
    ModelRegistry,
    RetrievalDatabaseConnector,
    Sandbox,
    init_rag_database,
    sandbox_setup,
)
from deadend_agent.hooks import set_event_hooks
from deadend_agent.tools.tool_wrappers import (
    set_approval_provider,
    enable_approval_mode,
    disable_approval_mode,
    is_approval_mode_enabled,
)
from deadend_agent.utils.network import check_target_alive

from .component_manager import ComponentManager
from .event_bus import EventBus, event_bus
from .hooks_adapter import EventBusHooksAdapter
from .rpc_models import RPCErrorCode


class RPCServer:
    def __init__(
        self,
        config: Optional[Config] = None,
        llm_provider: str = "openai",
    ) -> None:
        self.config = config or Config()
        self.config.configure()
        self.llm_provider = llm_provider

        # Event bus and hooks
        self.event_bus = event_bus
        self.hooks_adapter = EventBusHooksAdapter(self.event_bus)

        # Set global hooks so agents emit events
        set_event_hooks(self.hooks_adapter)

        # Set approval provider so tools can request approval via event bus
        set_approval_provider(self.event_bus)

        # Component manager
        self.component_manager = ComponentManager()

        # Shutdown flag
        self._shutdown_requested = False

        # Method dispatch table
        self._method_handlers: Dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {
            # Lifecycle
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
            # Initialization
            "init_docker": self._handle_init_docker,
            "init_pgvector": self._handle_init_pgvector,
            "init_config": self._handle_init_config,
            "init_python_sandbox": self._handle_init_python_sandbox,
            "init_shell_sandbox": self._handle_init_shell_sandbox,
            "init_playwright": self._handle_init_playwright,
            # Health checks
            "health_docker": self._handle_health_docker,
            "health_pgvector": self._handle_health_pgvector,
            "health_python_sandbox": self._handle_health_python_sandbox,
            "health_shell_sandbox": self._handle_health_shell_sandbox,
            "health_playwright": self._handle_health_playwright,
            "health_all": self._handle_health_all,
            # Event streaming
            "subscribe_events": self._handle_subscribe_events,
            # Control
            "interrupt": self._handle_interrupt,
            "approve": self._handle_approve,
            "enable_approval_mode": self._handle_enable_approval_mode,
            "disable_approval_mode": self._handle_disable_approval_mode,
            "get_approval_mode": self._handle_get_approval_mode,
            # Task execution
            "run_task": self._handle_run_task,
        }

    async def _run_task_stream(
        self,
        *,
        prompt: str,
        target: str,
        openapi_spec: Any | None = None,
        knowledge_base: str = "",
        mode: str = "yolo",
    ):
        model_registry = ModelRegistry(config=self.config)
        if not model_registry.has_any_model():
            raise RuntimeError(
                "No LM model configured. Run `deadend init` to initialize the model configuration."
            )

        model = model_registry.get_model(provider=self.llm_provider)
        embedder_client = model_registry.get_embedder_model()

        rag_db: RetrievalDatabaseConnector | None = None
        try:
            rag_db = await init_rag_database(self.config.db_url)
        except Exception as exc:
            raise RuntimeError(f"Vector DB not accessible: {exc}") from exc

        sandbox: Sandbox | None = None
        try:
            sandbox_manager = sandbox_setup()
            sandbox_id = sandbox_manager.create_sandbox(
                "xoxruns/sandboxed_kali", network_name="host"
            )
            sandbox = sandbox_manager.get_sandbox(sandbox_id=sandbox_id)
        except Exception:
            sandbox = None

        alive, status_code, err = await check_target_alive(target)
        if not alive:
            raise RuntimeError(
                f"Target not reachable (status={status_code}, error={err})"
            )

        available_agents = {
            "requester": (
                "Agent specialized in fine-grained testing and sending raw request data. "
                "Best for gathering auth tokens, testing individual endpoints, and precise "
                "request manipulation."
            ),
            "python_interpreter": (
                "Agent specialized in generating code and running it safely in a sandbox. "
                "Best for fuzzing, parameter testing, and repetitive security testing operations."
            ),
            "shell": "Agent providing access to a bash shell for running Linux commands.",
            "router_agent": "Router agent that selects the appropriate specialized agent.",
        }

        deadend_agent = DeadEndAgent(
            session_id=model.session_id if hasattr(model, "session_id") else model.model_id,
            model=model,
            available_agents=available_agents,
            max_depth=3,
        )

        async def approval_callback() -> str:
            return "yes"

        deadend_agent.set_approval_callback(approval_callback)

        deadend_agent.init_webtarget_indexer(target=target)
        await deadend_agent.crawl_target()
        code_chunks = await deadend_agent.embed_target(embedder_client=embedder_client)

        if rag_db is not None and self.config.openai_api_key and self.config.embedding_model:
            await rag_db.batch_insert_code_chunks(code_chunks_data=code_chunks)

        deadend_agent.prepare_dependencies(
            embedder_client=embedder_client,
            rag_connector=rag_db,
            sandbox=sandbox,
            target=target,
        )

        threat_model_text = ""
        async for item in deadend_agent.threat_model_stream(task=prompt):
            threat_model_text += self._to_string(item)
            yield {
                "phase": "recon",
                "data": self._to_serializable(item),
            }

        async for item in deadend_agent.start_testing_stream(
            task=prompt,
            threat_model=threat_model_text,
        ):
            yield {
                "phase": "exploit",
                "data": self._to_serializable(item),
            }

        yield {
            "phase": "done",
            "mode": mode,
            "target": target,
            "openapi_spec": openapi_spec,
            "knowledge_base": knowledge_base,
        }

    def serve(self) -> None:
        """Start the RPC server with signal handling."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Set up signal handlers for graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        try:
            loop.run_until_complete(self._serve_loop())
        finally:
            loop.close()

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        self._shutdown_requested = True

    async def _serve_loop(self) -> None:
        """Main async serve loop with non-blocking stdin reading."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin
        )

        while not self._shutdown_requested:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            if not line:
                # EOF
                break

            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            async for response in self._handle_request_stream(request):
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        # Graceful shutdown
        await self.component_manager.shutdown()

    async def _handle_request_stream(
        self,
        request: Dict[str, Any],
    ):
        """Handle a JSON-RPC request and yield responses."""
        jsonrpc = request.get("jsonrpc")
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if jsonrpc != "2.0":
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": RPCErrorCode.INVALID_REQUEST,
                    "message": "Invalid JSON-RPC version",
                },
            }
            return

        handler = self._method_handlers.get(method)
        if handler is None:
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": RPCErrorCode.METHOD_NOT_FOUND,
                    "message": f"Unknown method: {method}",
                },
            }
            return

        try:
            result = await handler(request_id, params)
            # Check if result is an async generator (for streaming methods)
            if hasattr(result, "__aiter__"):
                async for item in result:
                    yield {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": item,
                    }
            else:
                yield {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
        except Exception as exc:
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": RPCErrorCode.INTERNAL_ERROR,
                    "message": str(exc),
                },
            }

    # =========================================================================
    # Handler methods
    # =========================================================================

    async def _handle_ping(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ping request."""
        return {"status": "ok"}

    async def _handle_shutdown(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle shutdown request."""
        self._shutdown_requested = True
        result = await self.component_manager.shutdown()
        return {"status": "shutdown", "components": result}

    async def _handle_init_docker(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize Docker component."""
        result = await self.component_manager.init_docker()
        return result.model_dump()

    async def _handle_init_pgvector(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize pgvector database."""
        result = await self.component_manager.init_pgvector()
        return result.model_dump()

    async def _handle_init_config(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize configuration."""
        result = await self.component_manager.init_config()
        return result.model_dump()

    async def _handle_init_python_sandbox(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize Python sandbox."""
        result = await self.component_manager.init_python_sandbox()
        return result.model_dump()

    async def _handle_init_shell_sandbox(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize shell sandbox."""
        result = await self.component_manager.init_shell_sandbox()
        return result.model_dump()

    async def _handle_init_playwright(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize Playwright browser."""
        result = await self.component_manager.init_playwright()
        return result.model_dump()

    async def _handle_health_docker(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check Docker health."""
        result = await self.component_manager.health_docker()
        return result.model_dump()

    async def _handle_health_pgvector(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check pgvector health."""
        result = await self.component_manager.health_pgvector()
        return result.model_dump()

    async def _handle_health_python_sandbox(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check Python sandbox health."""
        result = await self.component_manager.health_python_sandbox()
        return result.model_dump()

    async def _handle_health_shell_sandbox(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check shell sandbox health."""
        result = await self.component_manager.health_shell_sandbox()
        return result.model_dump()

    async def _handle_health_playwright(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check Playwright health."""
        result = await self.component_manager.health_playwright()
        return result.model_dump()

    async def _handle_health_all(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check all components health."""
        result = await self.component_manager.health_all()
        return result.model_dump()

    async def _handle_subscribe_events(self, request_id: Any, params: Dict[str, Any]):
        """Subscribe to event stream. This is a streaming method."""
        async for event in self.event_bus.subscribe():
            yield event.model_dump()

    async def _handle_interrupt(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Interrupt a running workflow."""
        session_id = params.get("session_id")
        if not session_id:
            raise ValueError("session_id is required")

        reason = params.get("reason", "User requested interruption")
        self.event_bus.interrupt_session(session_id, reason)
        return {"status": "interrupted", "session_id": session_id}

    async def _handle_approve(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Respond to an approval request."""
        approval_request_id = params.get("request_id")
        if not approval_request_id:
            raise ValueError("request_id is required")

        approved = params.get("approved", False)
        modified_args = params.get("modified_args")

        success = self.event_bus.respond_to_approval(
            request_id=approval_request_id,
            approved=approved,
            modified_args=modified_args,
        )

        if not success:
            raise ValueError(f"Approval request {approval_request_id} not found or already processed")

        return {"status": "approved" if approved else "rejected", "request_id": approval_request_id}

    async def _handle_enable_approval_mode(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Enable approval mode - all tool calls require user approval."""
        enable_approval_mode()
        return {"status": "enabled", "approval_mode": True}

    async def _handle_disable_approval_mode(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Disable approval mode - tools execute without approval."""
        disable_approval_mode()
        return {"status": "disabled", "approval_mode": False}

    async def _handle_get_approval_mode(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current approval mode status."""
        return {"approval_mode": is_approval_mode_enabled()}

    async def _handle_run_task(self, request_id: Any, params: Dict[str, Any]):
        """Run a task. This is a streaming method."""
        async for event in self._run_task_stream(**params):
            yield event

    def _to_string(self, obj: Any) -> str:
        if obj is None:
            return ""
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(), default=str)
        return str(obj)

    def _to_serializable(self, obj: Any) -> Any:
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: self._to_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._to_serializable(v) for v in obj]
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if is_dataclass(obj):
            return asdict(obj)
        return repr(obj)


__all__ = ["RPCServer"]
