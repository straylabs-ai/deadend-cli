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
from typing import Any, AsyncGenerator, Callable, Dict, Optional
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from dataclasses import asdict, is_dataclass

from deadend_agent import DeadEndAgent, Sandbox
from deadend_agent.hooks import set_event_hooks
from deadend_agent.tools.tool_wrappers import (
    set_approval_provider,
    enable_approval_mode,
    disable_approval_mode,
    is_approval_mode_enabled,
)
from deadend_agent.utils.network import check_target_alive
from deadend_agent.core_agent import (
    LLMError,
    RateLimitError,
    QuotaExceededError,
    AuthenticationError,
    ConnectionError as LLMConnectionError,
    ModelNotFoundError,
    InvalidRequestError,
)

from .component_manager import ComponentManager
from .event_bus import event_bus
from .hooks_adapter import EventBusHooksAdapter
from .logging import logger, setup_logging
from .rpc_models import RPCErrorCode


# JSON-RPC 2.0 error codes (use RPCErrorCode from rpc_models for custom codes)
class JSONRPCErrorCode:
    """JSON-RPC 2.0 standard error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


def _make_jsonrpc_response(request_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a JSON-RPC 2.0 response."""
    response: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response


def _make_jsonrpc_error(request_id: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    """Create a JSON-RPC 2.0 error response."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return _make_jsonrpc_response(request_id, error=error)


class RPCServer:
    def __init__(
        self,
        llm_provider: str = "openai",
        debug: bool = False,
        log_file: Optional[str] = None,
    ) -> None:
        # Setup logging first so all subsequent operations are logged
        log_level = logging.DEBUG if debug else logging.INFO
        setup_logging(level=log_level, log_file=log_file)
        logger.info("RPC Server initializing...")
        if debug:
            logger.debug("Debug logging enabled")

        # CRITICAL: Save original stdout for RPC communication, then redirect
        # sys.stdout to stderr. This ensures all print() statements from any
        # module go to stderr instead of polluting the JSON-RPC communication.
        self._rpc_stdout = sys.stdout
        sys.stdout = sys.stderr
        logger.debug("Redirected sys.stdout to stderr for clean RPC communication")

        # Force RPC stdout to be line-buffered for immediate streaming
        # This is critical when running as a subprocess (not attached to TTY)
        if not self._rpc_stdout.isatty():
            try:
                # Python 3.7+ - reconfigure to line buffering
                self._rpc_stdout.reconfigure(line_buffering=True)
            except (AttributeError, OSError):
                # Fallback for older Python versions or when reconfigure fails
                try:
                    # Reopen stdout in line-buffered mode
                    self._rpc_stdout = os.fdopen(self._rpc_stdout.fileno(), 'w', buffering=1)
                except (OSError, AttributeError):
                    # If that fails, at least ensure we flush aggressively
                    logger.warning("Could not configure stdout buffering, will flush aggressively")

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

        #

        # Shutdown flag
        self._shutdown_requested = False

        # Method dispatch table
        self._method_handlers: Dict[str, Callable[..., AsyncGenerator[Any, Any]]] = {
            # Lifecycle
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
            # Initialization
            "init_all": self._handle_init_all,
            "init_docker": self._handle_init_docker,
            "init_pgvector": self._handle_init_pgvector,
            "init_config": self._handle_init_config,
            "init_model_registry": self._handle_init_model_registry,
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
            # LLM provider management
            "list_llm_providers": self._handle_list_llm_providers,
            "get_llm_provider": self._handle_get_llm_provider,
            "set_llm_provider": self._handle_set_llm_provider,
            # Task execution
            "run_task": self._handle_run_task,
        }

    async def _run_task_stream(
        self,
        *,
        prompt: str,
        target: str,
        mode: str = "yolo",
    ):
        try:
            # Yield initial event IMMEDIATELY to signal task has started
            # This must be the very first thing that happens
            yield {
                "phase": "init",
                "data": {"message": "Task started", "target": target, "prompt": prompt},
            }
            
            # Give the event loop a chance to send the first message before heavy work
            await asyncio.sleep(0.01)

            yield {
                "phase": "init",
                "data": {"message": "Checking component readiness..."},
            }

            # Verify all required components are initialized (this might be blocking)
            # Yield before and after to ensure streaming continues
            await asyncio.sleep(0)  # Yield control to event loop
            is_ready, missing = self.component_manager.is_ready_for_tasks()
            await asyncio.sleep(0)  # Yield control again after sync call
            
            if not is_ready:
                raise RuntimeError(
                    f"Components not initialized: {', '.join(missing)}. "
                    "Call init_all or initialize individual components first."
                )

            yield {
                "phase": "init",
                "data": {"message": "Verifying target reachability..."},
            }
            await asyncio.sleep(0)  # Yield before potentially blocking network call

            # Check if target is reachable
            alive, status_code, err = await check_target_alive(target)
            if not alive:
                raise RuntimeError(
                    f"Target not reachable (status={status_code}, error={err})"
                )

            yield {
                "phase": "init",
                "data": {"message": "Initializing agent..."},
            }
            await asyncio.sleep(0)  # Yield before potentially blocking calls

            # Get pre-initialized components (use current provider from component manager)
            # These might be blocking, so yield between them
            model = self.component_manager.get_model()
            await asyncio.sleep(0)
            embedder_client = self.component_manager.get_embedder()
            await asyncio.sleep(0)
            rag_db = self.component_manager.get_rag_connector()
            await asyncio.sleep(0)

            # Create a sandbox for this task
            sandbox: Sandbox | None = None
            try:
                sandbox = self.component_manager.create_task_sandbox(network_name="host")
            except Exception as e:
                logger.warning("Failed to create sandbox: %s", e)
                sandbox = None

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

            # Generate a unique session ID for this task
            task_session_id = uuid.uuid4()

            deadend_agent = DeadEndAgent(
                session_id=task_session_id,
                model=model,
                available_agents=available_agents,
                max_depth=3,
            )

            async def approval_callback() -> str:
                return "yes"

            deadend_agent.set_approval_callback(approval_callback)

            yield {
                "phase": "init",
                "data": {"message": "Crawling target..."},
            }

            deadend_agent.init_webtarget_indexer(target=target)
            await deadend_agent.crawl_target()

            yield {
                "phase": "init",
                "data": {"message": "Embedding target code..."},
            }

            code_chunks = await deadend_agent.embed_target(embedder_client=embedder_client)

            config = self.component_manager.config
            if rag_db is not None and config.openai_api_key and config.embedding_model:
                yield {
                    "phase": "init",
                    "data": {"message": "Storing embeddings in database..."},
                }
                await rag_db.batch_insert_code_chunks(code_chunks_data=code_chunks)

            deadend_agent.prepare_dependencies(
                embedder_client=embedder_client,
                rag_connector=rag_db,
                sandbox=sandbox,
                target=target,
            )

            yield {
                "phase": "init",
                "data": {"message": "Starting threat modeling..."},
            }

            threat_model_text = ""
            async for item in deadend_agent.threat_model_stream(task=prompt):
                threat_model_text += self._to_string(item)
                yield {
                    "phase": "recon",
                    "data": self._to_serializable(item),
                }

            yield {
                "phase": "init",
                "data": {"message": "Starting exploitation phase..."},
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
            }
        except Exception as exc:
            logger.exception(f"Error in _run_task_stream: {exc}")
            yield {
                "phase": "error",
                "data": {
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            }
            raise

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

        # Track active request handlers for concurrent processing
        active_tasks: set[asyncio.Task] = set()

        while not self._shutdown_requested:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.1)
            except asyncio.TimeoutError:
                # Clean up completed tasks
                active_tasks = {t for t in active_tasks if not t.done()}
                continue

            if not line:
                # EOF - wait for all tasks to complete
                if active_tasks:
                    await asyncio.gather(*active_tasks, return_exceptions=True)
                break

            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            # Process request in a task to allow concurrent handling
            task = asyncio.create_task(self._handle_request_and_write(request))
            active_tasks.add(task)
            task.add_done_callback(active_tasks.discard)

        # Graceful shutdown
        await self.component_manager.shutdown()

    async def _handle_request_and_write(self, request: Dict[str, Any]) -> None:
        """Handle a request and write all streaming responses."""
        try:
            async for response in self._handle_request_stream(request):
                # Ensure all responses are JSON serializable (e.g. datetimes) and
                # never emit non-JSON text on stdout, as the CLI expects NDJSON.
                serializable = self._to_serializable(response)
                json_str = json.dumps(serializable, default=str)
                self._rpc_stdout.write(json_str + "\n")
                self._rpc_stdout.flush()
                # Force immediate write for streaming (fsync if possible)
                try:
                    if hasattr(self._rpc_stdout, 'fileno'):
                        os.fsync(self._rpc_stdout.fileno())
                except (OSError, AttributeError):
                    # Not all file descriptors support fsync, that's okay
                    pass
        except Exception as e:
            logger.exception("Error handling request: %s", e)

    async def _handle_request_stream(
        self,
        request: Dict[str, Any],
    ):
        """Handle a JSON-RPC request and yield responses."""
        # Validate JSON-RPC request format
        if not isinstance(request, dict):
            yield _make_jsonrpc_error(
                request_id=request.get("id") if isinstance(request, dict) else None,
                code=JSONRPCErrorCode.INVALID_REQUEST,
                message="Invalid JSON-RPC request: must be an object",
            )
            return

        # Check for required fields
        if "jsonrpc" not in request or request.get("jsonrpc") != "2.0":
            yield _make_jsonrpc_error(
                request_id=request.get("id"),
                code=JSONRPCErrorCode.INVALID_REQUEST,
                message="Invalid JSON-RPC request: missing or invalid 'jsonrpc' field",
            )
            return

        if "method" not in request:
            yield _make_jsonrpc_error(
                request_id=request.get("id"),
                code=JSONRPCErrorCode.INVALID_REQUEST,
                message="Invalid JSON-RPC request: missing 'method' field",
            )
            return

        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if not isinstance(method, str):
            yield _make_jsonrpc_error(
                request_id=request_id,
                code=JSONRPCErrorCode.INVALID_REQUEST,
                message="Invalid JSON-RPC request: 'method' must be a string",
            )
            return

        handler = self._method_handlers.get(method)
        if handler is None:
            yield _make_jsonrpc_error(
                request_id=request_id,
                code=JSONRPCErrorCode.METHOD_NOT_FOUND,
                message=f"Unknown method: {method}",
            )
            return

        try:
            # Call the handler - it might return a coroutine or an async generator
            handler_result = handler(request_id, params)
            
            # Check if handler returned an async generator (async generator functions return generators immediately)
            if hasattr(handler_result, "__aiter__"):
                # Handler returned an async generator - iterate over it directly
                async for item in handler_result:
                    yield _make_jsonrpc_response(request_id=request_id, result=item)
            elif asyncio.iscoroutine(handler_result):
                # Handler returned a coroutine - await it
                result = await handler_result
                # Check if the awaited result is an async generator
                if hasattr(result, "__aiter__"):
                    async for item in result:
                        yield _make_jsonrpc_response(request_id=request_id, result=item)
                else:
                    yield _make_jsonrpc_response(request_id=request_id, result=result)
            else:
                # Handler returned a regular value
                yield _make_jsonrpc_response(request_id=request_id, result=handler_result)
        except Exception as exc:
            # Map exceptions to JSON-RPC error codes
            error_code = JSONRPCErrorCode.INTERNAL_ERROR
            error_message = str(exc)

            if isinstance(exc, ValueError):
                error_code = JSONRPCErrorCode.INVALID_PARAMS
            elif isinstance(exc, QuotaExceededError):
                error_code = RPCErrorCode.LLM_QUOTA_EXCEEDED
            elif isinstance(exc, RateLimitError):
                error_code = RPCErrorCode.LLM_RATE_LIMIT
            elif isinstance(exc, AuthenticationError):
                error_code = RPCErrorCode.LLM_AUTH_ERROR
            elif isinstance(exc, LLMConnectionError):
                error_code = RPCErrorCode.LLM_CONNECTION_ERROR
            elif isinstance(exc, ModelNotFoundError):
                error_code = RPCErrorCode.LLM_MODEL_NOT_FOUND
            elif isinstance(exc, InvalidRequestError):
                error_code = RPCErrorCode.LLM_INVALID_REQUEST
            elif isinstance(exc, LLMError):
                error_code = RPCErrorCode.LLM_ERROR

            yield _make_jsonrpc_error(
                request_id=request_id,
                code=error_code,
                message=error_message,
            )

    # =========================================================================
    # Handler methods
    # =========================================================================

    async def _handle_ping(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle ping request."""
        return {"status": "ok"}

    async def _handle_shutdown(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle shutdown request."""
        self._shutdown_requested = True
        result = await self.component_manager.shutdown()
        return {"status": "shutdown", "components": result}

    async def _handle_init_all(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize all components in the correct order."""
        logger.info("Starting initialization of all components...")
        result = await self.component_manager.init_all()
        return result.model_dump()

    async def _handle_init_docker(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize Docker component."""
        result = await self.component_manager.init_docker()
        return result.model_dump()

    async def _handle_init_pgvector(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize pgvector database."""
        result = await self.component_manager.init_pgvector()
        return result.model_dump()

    async def _handle_init_config(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize configuration."""
        result = await self.component_manager.init_config()
        return result.model_dump()

    async def _handle_init_model_registry(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize model registry."""
        result = await self.component_manager.init_model_registry()
        return result.model_dump()

    async def _handle_init_python_sandbox(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize Python sandbox."""
        result = await self.component_manager.init_python_sandbox()
        return result.model_dump()

    async def _handle_init_shell_sandbox(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
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

    async def _handle_health_playwright(
        self, 
        request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
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

    async def _handle_enable_approval_mode(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enable approval mode - all tool calls require user approval."""
        enable_approval_mode()
        return {"status": "enabled", "approval_mode": True}

    async def _handle_disable_approval_mode(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Disable approval mode - tools execute without approval."""
        disable_approval_mode()
        return {"status": "disabled", "approval_mode": False}

    async def _handle_get_approval_mode(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current approval mode status."""
        return {"approval_mode": is_approval_mode_enabled()}

    async def _handle_list_llm_providers(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """List all available LLM providers and their configuration status."""
        result = self.component_manager.list_llm_providers()
        return result

    async def _handle_get_llm_provider(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get the current LLM provider."""
        provider = self.component_manager.get_llm_provider()
        return {"provider": provider}

    async def _handle_set_llm_provider(
        self,
        request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Set the current LLM provider."""
        provider = params.get("provider")
        if not provider:
            raise ValueError("provider parameter is required")
        
        self.component_manager.set_llm_provider(provider)
        # Update the server's llm_provider attribute for consistency
        self.llm_provider = provider
        
        return {"status": "ok", "provider": provider}

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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DeadEnd RPC Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-file", type=str, help="Log file path")
    parser.add_argument(
        "--llm-provider",
        type=str,
        default="openai",
        help="LLM provider to use (openai, anthropic, gemini, openrouter, local)",
    )
    args = parser.parse_args()

    server = RPCServer(
        llm_provider=args.llm_provider,
        debug=args.debug,
        log_file=args.log_file,
    )
    server.serve()
