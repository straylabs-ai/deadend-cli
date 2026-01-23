# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

""" JsonRPC server interface """
from typing import Any, Dict
import typer
from deadend_agent import set_event_hooks
from deadend_agent.tools.tool_wrappers import (
    set_approval_provider,
    enable_approval_mode,
    disable_approval_mode,
    is_approval_mode_enabled
)
from deadend_cli.logging import logger
from deadend_cli.component_manager import ComponentManager
from deadend_cli.jsonrpc.rpc_server import RPCServer
from deadend_cli.jsonrpc.event_bus import EventBus
from deadend_cli.jsonrpc.hooks_adapter import EventBusHooksAdapter


def main(
    debug: bool=False,
    log_file: str = "./",
):
    """Start the JSON-RPC server for communicating with front-end components.
    
    This function initializes the RPC server that handles JSON-RPC requests over
    stdio. The server supports component initialization, health checks, event
    streaming, and workflow management.
    
    Args:
        debug: If True, enable debug-level logging. Defaults to False.
        log_file: Path to the log file. Defaults to "./".
    
    Returns:
        None. The server runs until interrupted or shutdown is requested.
    """

    # Initializing the component manager
    component_manager = ComponentManager()

    event_bus = EventBus()
    # Event Bus and hooks
    hooks_adapter = EventBusHooksAdapter(event_bus=event_bus)

    # Global hooks for emitting events by the agent
    set_event_hooks(hooks_adapter)
    # Approval provider giving the possibility for tools to request approval via event bus
    set_approval_provider(event_bus)
    # Shutdown Request
    shutdown_request = False

    # Initializing the rpc server with it's logging debug and log file
    server = RPCServer(
        debug=debug,
        log_file=log_file
    )

    server.add_dependency("component_manager", component_manager)
    server.add_dependency("event_bus", event_bus)

    # # AI model
    # llm_provider = "openai"

    # ==========================================
    # Init methods
    # ==========================================
    @server.add_method("ping")
    async def ping(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle ping request."""
        return {"status": "ok"}

    @server.add_method("shutdown")
    async def shutdown(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Handle shutdown request."""
        # self._shutdown_requested = True
        result = await component_manager.shutdown()
        return {"status": "shutdown", "components": result}

    @server.add_method("init_all")
    async def init_all(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize all components in the correct order."""
        logger.info("Starting initialization of all components...")
        result = await component_manager.init_all()
        return result.model_dump()

    @server.add_method("init_docker")
    async def init_docker(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize Docker component."""
        result = await component_manager.init_docker()
        return result.model_dump()

    @server.add_method("init_pgvector")
    async def init_pgvector(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize pgvector database."""
        result = await component_manager.init_pgvector()
        return result.model_dump()

    @server.add_method("init_config")
    async def init_config(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize configuration."""
        result = await component_manager.init_config()
        return result.model_dump()

    @server.add_method("init_model_registry")
    async def init_model_registry(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize model registry."""
        result = await component_manager.init_model_registry()
        return result.model_dump()

    @server.add_method("init_python_sandbox")
    async def init_python_sandbox(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize Python sandbox."""
        result = await component_manager.init_python_sandbox()
        return result.model_dump()

    @server.add_method("init_shell_sandbox")
    async def init_shell_sandbox(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize shell sandbox."""
        result = await component_manager.init_shell_sandbox()
        return result.model_dump()


    @server.add_method("init_playwright")
    async def init_playwright(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize Playwright browser."""
        result = await component_manager.init_playwright()
        return result.model_dump()

    @server.add_method("health_docker")
    async def health_docker(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check Docker health."""
        result = await component_manager.health_docker()
        return result.model_dump()

    @server.add_method("health_pgvector")
    async def health_pgvector(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check pgvector health."""
        result = await component_manager.health_pgvector()
        return result.model_dump()

    @server.add_method("health_python_sandbox")
    async def health_python_sandbox(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check Python sandbox health."""
        result = await component_manager.health_python_sandbox()
        return result.model_dump()

    @server.add_method("health_shell_sandbox")
    async def health_shell_sandbox(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check shell sandbox health."""
        result = await component_manager.health_shell_sandbox()
        return result.model_dump()

    @server.add_method("health_playwright")
    async def health_playwright(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check Playwright health."""
        result = await component_manager.health_playwright()
        return result.model_dump()

    @server.add_method("health_all")
    async def health_all(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check all components health."""
        result = await component_manager.health_all()
        return result.model_dump()

    # ==========================================
    # Handler methods
    # ==========================================
    @server.add_method("subscribe_events")
    async def subscribe_events(
        _request_id: Any,
        _params: Dict[str, Any],
        event_bus: EventBus
    ) -> Dict[str, Any]:
        async for event in event_bus.subscribe():
            yield event.model_dump()
    
    @server.add_method("interrupt")
    async def handle_interrupt(
        _request_id: Any,
        params: Dict[str, Any],
        event_bus: EventBus
    ) -> Dict[str, Any]:
        session_id = params.get("session_id")
        if not session_id:
            raise ValueError("Session ID required.")
        reason = params.get("reason", "User request interruption")
        event_bus.interrupt_session(session_id, reason)
        return {
            "status": "interrupted",
            "session_id": session_id
        }

    @server.add_method("approve")
    async def handle_approval(
        _request_id: Any,
        params: Dict[str, Any],
        event_bus: EventBus
    ) -> Dict[str, Any]:
        approval_request_id = params.get("request_id")
        if not approval_request_id:
            raise ValueError("request_id is required.")
        approved = params.get("approved", False)
        modified_args = params.get("modified_args")

        success = event_bus.respond_to_approval(
            request_id=approval_request_id,
            approved=approved,
            modified_args=modified_args
        )
        if not success:
            raise ValueError(f"Approval request {approval_request_id} not found or already processed")
        return {"status": "approved" if approved else "rejected", "request_id": approval_request_id}

    @server.add_method("enable_approval_mode")
    async def enable_approval(
        _request_id: Any,
        _params: Dict[str, Any],
        event_bus: EventBus
    ) -> Dict[str, Any]:
        """Enable approval mode - all tool calls require user approval."""
        enable_approval_mode()
        return {"status": "enabled", "approval_mode": True}

    @server.add_method("disable_approval_mode")
    async def disable_approval(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Disable approval mode - tools execute without approval."""
        disable_approval_mode()
        return {"status": "disabled", "approval_mode": False}
    
    @server.add_method("get_approval")
    async def get_approval_mode(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get current approval mode status."""
        return {"approval_mode": is_approval_mode_enabled()}
    
    # ==========================================
    # LLM provider methods
    # ==========================================
    @server.add_method("list_llm_provider")
    async def list_llm_providers(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """List all available LLM providers and their configuration status."""
        result = component_manager.list_llm_providers()
        return result
    # TODO: the get llm provider should return the provider AND the model currently used
    # otherwise we can't set it up correctly
    @server.add_method("get_llm_provider")
    async def get_llm_provider(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """List all available LLM providers and their configuration status."""
        provider = component_manager.get_llm_provider()
        return {"provider": provider}
    # TODO: The set provider here, only sets up the provider and not the model itself, or the
    # API KEY nor the base url if needed, this is a problem
    # 
    @server.add_method("set_llm_provider")
    async def set_llm_provider(
        _request_id: Any,
        params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Set the current LLM provider."""
        provider = params.get("provider")
        if not provider:
            raise ValueError("provider parameter is required")

        component_manager.set_llm_provider(provider)
        # Update the server's llm_provider attribute for consistency
        # llm_provider = provider

        return {"status": "ok", "provider": provider}

    @server.add_method("embed_target")
    async def embed_target(
        _request_id: Any,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        pass

    server.serve()

if __name__ == "__main__":
    typer.run(main)