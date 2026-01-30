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
from typing import Any, Callable, Dict, Optional
import asyncio
import inspect
import json
import logging
import os
import signal
import sys
import uuid
from dataclasses import asdict, is_dataclass

from deadend_agent.core_agent import (
    LLMError,
    RateLimitError,
    QuotaExceededError,
    AuthenticationError,
    ConnectionError as LLMConnectionError,
    ModelNotFoundError,
    InvalidRequestError,
)

from ..cli_logging import logger, setup_logging
from .rpc_models import RPCErrorCode


# JSON-RPC 2.0 error codes (use RPCErrorCode from rpc_models for custom codes)
class JSONRPCErrorCode:
    """JSON-RPC 2.0 standard error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

def _make_jsonrpc_response(
    request_id: Any,
    result: Any = None,
    error: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
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

        # Store dependencies injected in RPC calls
        self._dependencies: Dict[str, Any] = {}

        # Shutdown flag
        self._shutdown_requested = False

        # Method handler keeps track of the RPC methods used
        self._method_handlers: Dict[str, Callable[..., Any]] = {}

        # Shutdown callbacks for graceful cleanup
        self._shutdown_callbacks: list[Callable[[], Any]] = []

    def add_dependency(self, name: str, value: Any) -> None:
        """Register a new dependency used by the RPC methods"""
        self._dependencies[name] = value

    def add_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Register a callback to be called during graceful shutdown.
        
        The callback should be an async function or a regular function.
        It will be awaited if it's a coroutine.
        """
        self._shutdown_callbacks.append(callback)

    def add_method(self, method_name: str, **dependencies):
        """Decorator to register new methods to the rpc server.
    
        Usage:
        rpc_server = RPCServer()
        
        @rpc_server.method("ping")
        async def ping(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
            return {"status": "ok"}
        
        rpc_server.serve()
        """
        def decorator(func: Callable) -> Callable:
            # Get the function signature to check which parameters it accepts
            sig = inspect.signature(func)
            param_names = set(sig.parameters.keys())
            # Exclude request_id and params as they're always provided
            param_names.discard('request_id')
            param_names.discard('_request_id')
            param_names.discard('params')
            param_names.discard('_params')
            
            # Check if the function is an async generator function
            is_async_gen = inspect.isasyncgenfunction(func)

            async def wrapped_call(request_id: Any, params: Dict[str, Any]):
                injected = {}

                # Add dependencies explicitly passed to the decorator
                for dep_name, dep_value in dependencies.items():
                    if dep_name in param_names:
                        injected[dep_name] = dep_value

                # Add dependencies from registered dependencies that match function parameters
                for dep_name, dep_value in self._dependencies.items():
                    if dep_name not in injected and dep_name in param_names:
                        injected[dep_name] = dep_value

                if injected:
                    result = func(request_id, params, **injected)
                else:
                    result = func(request_id, params)

                # For async generator functions, return the generator directly
                # For regular async functions, await the coroutine
                if is_async_gen:
                    return result
                else:
                    return await result
            # Registering the new method part of the RPC server.

            self._method_handlers[method_name] = wrapped_call
            logger.debug("RPC method added : %s", method_name)
            return wrapped_call
        return decorator

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

        logger.info("RPC Server started and listening on stdin")
        
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
                logger.debug("Received JSON-RPC request: method=%s, id=%s", request.get("method"), request.get("id"))
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse JSON-RPC request: %s %s",e, line_str[:100])
                continue

            # Process request in a task to allow concurrent handling
            task = asyncio.create_task(self._handle_request_and_write(request))
            active_tasks.add(task)
            task.add_done_callback(active_tasks.discard)

        # Graceful shutdown - call all registered shutdown callbacks
        if self._shutdown_callbacks:
            logger.info("Executing shutdown callbacks...")
            for callback in self._shutdown_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        result = callback()
                        if asyncio.iscoroutine(result):
                            await result
                except Exception as e:
                    logger.exception("Error in shutdown callback: %s", e)

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
