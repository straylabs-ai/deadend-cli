# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

""" JsonRPC server interface """
from typing import Any, Dict, AsyncGenerator
import json
from dataclasses import asdict, is_dataclass
from pydantic import TypeAdapter
import typer
import uuid
from deadend_agent import DeadEndAgent, Sandbox, config_setup, set_event_hooks
from deadend_agent.utils.network import deterministic_session_id
from deadend_agent.tools.tool_wrappers import (
    set_approval_provider,
    enable_approval_mode,
    disable_approval_mode,
    is_approval_mode_enabled
)
from deadend_cli.cli_logging import logger
from deadend_cli.component_manager import ComponentManager
from deadend_cli.jsonrpc.rpc_server import RPCServer
from deadend_cli.jsonrpc.event_bus import EventBus
from deadend_cli.jsonrpc.hooks_adapter import EventBusHooksAdapter


def main(
    debug: bool=False,
    log_file: str | None = None,
):
    """Start the JSON-RPC server for communicating with front-end components.
    
    This function initializes the RPC server that handles JSON-RPC requests over
    stdio. The server supports component initialization, health checks, event
    streaming, and workflow management.
    
    Args:
        debug: If True, enable debug-level logging. Defaults to False.
        log_file: Path to the log file. If None, logs only to stderr. Defaults to None.
    
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

    # Agent reference instantiation keeps a reference
    # to a agent instantiated. This is basically a workaround
    # to keep a instance usable accross the different calls.
    # If I find a better way to this I will change it; somehow
    # it doesn't feel like clean code
    deadend_agent_refs: Dict[str, DeadEndAgent] = {}

    # Initializing the rpc server with it's logging debug and log file
    server = RPCServer(
        debug=debug,
        log_file=log_file
    )

    server.add_dependency("component_manager", component_manager)
    server.add_dependency("event_bus", event_bus)
    server.add_dependency("deadend_agent_refs", deadend_agent_refs)

    # Register shutdown callback for graceful cleanup
    async def shutdown_callback():
        """Gracefully shutdown all components when server exits."""
        logger.info("Shutting down components...")
        await component_manager.shutdown()

    server.add_shutdown_callback(shutdown_callback)

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
    
    @server.add_method("get_approval_mode")
    async def get_approval_mode(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get current approval mode status."""
        return {"approval_mode": is_approval_mode_enabled()}



    # ==========================================
    # LLM provider methods
    # ==========================================
    @server.add_method("get_all_models")
    async def get_all_models(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """List all available and configured models in the config.json."""
        result = component_manager.get_all_models()
        return result
    @server.add_method("get_llm_provider")
    async def get_llm_provider(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Get the current LLM provider and model name."""
        provider = component_manager.get_llm_provider()
        
        # Get the model spec to extract model name
        try:
            model_spec = component_manager.get_model(provider=provider)
            return {
                "provider": provider,
                "model": model_spec.model_name
            }
        except (RuntimeError, ValueError) as e:
            # If we can't get the model, just return the provider
            logger.warning("Could not get model spec for provider %s: %s", provider, e)
            return {
                "provider": provider,
                "model": None
            }
    # TODO: The set provider here, only sets up the provider and not the model itself, or the
    # API KEY nor the base url if needed, this is a problem
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

    @server.add_method("add_model")
    async def add_model(
        _request_id: Any,
        params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Add a new model provider to the configuration.
        
        Args:
            params: Dictionary containing:
                - provider: Provider name (e.g., "openai", "anthropic")
                - model_name: Model name
                - api_key: API key (optional)
                - base_url: Base URL (optional)
                - type_model: Type of model, "embeddings" for embedding models (optional)
                - vec_dim: Vector dimension for embedding models (optional)
        
        Returns:
            Dictionary with status and provider information
        """
        if component_manager.config is None:
            raise RuntimeError("Configuration not initialized")

        provider = params.get("provider")
        model_name = params.get("model_name")
        api_key = params.get("api_key")
        base_url = params.get("base_url")
        type_model = params.get("type_model")
        vec_dim = params.get("vec_dim")

        if not provider or not model_name:
            raise ValueError("provider and model_name are required")

        # Add provider to the config and save to config.json
        component_manager.add_model_provider(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            type_model=type_model,
            vec_dim=vec_dim
        )

        # If it's a regular model (not embedding), optionally set it as the current provider
        if type_model != "embeddings" and component_manager.model_registry:
            try:
                component_manager.set_llm_provider(provider)
            except (ValueError, RuntimeError):
                # Provider might not be in registry yet, that's okay
                pass

        return {
            "status": "ok",
            "provider": provider,
            "model_name": model_name,
            "type_model": type_model or None
        }



    # ==========================================
    # Agent methods methods
    # ==========================================
    @server.add_method("instantiate_agent")
    async def instantiate_agent(
        _request_id: Any,
        params: Dict[str, Any],
        component_manager: ComponentManager,
        deadend_agent_refs: Dict[str, DeadEndAgent]
    ) -> Dict[str, Any]:
        # Validate parameters first
        target = params.get("target")
        if not target:
            return {
                "status": "failed",
                "reason": "Must supply a target"
            }

        # Get provider and model from params, or use current defaults
        provider = params.get("provider")
        model_name = params.get("model_name")

        # Get the model spec (will use current provider/model if not specified)
        logger.info("model and provider %s %s", provider, model_name)
        try:
            model = component_manager.get_model(provider=provider, model_name=model_name)
        except (RuntimeError, ValueError) as e:
            return {
                "status": "failed",
                "reason": f"Failed to get model: {str(e)}"
            }

        agent_id = uuid.uuid4()
        runtime_session_id = uuid.uuid4()
        embedding_session_id = deterministic_session_id(target)

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
            "webapp_analyzer": (
                "Front-end webapp analyzer. This agent is specialized in looking into the web application"
                "to be able to extract information about the logic details of the application. "
                "We can look for forms, API endpoints, website logic and forms"
            )
        }
        deadend_agent = DeadEndAgent(
            session_id=runtime_session_id,
            embedding_session_id=embedding_session_id,
            model=model,
            available_agents=available_agents,
            max_depth=3
        )
        async def approval_callback() -> str:
            return "yes"

        # Sandbox instantiation for the agent
        sandbox: Sandbox | None = None
        try:
            sandbox = component_manager.create_task_sandbox(network_name="host")
        except Exception as e:
            logger.error("Failed to create sandbox: %s", e)
            return {
                "status": "failed",
                "reason": f"Failed to create sandbox: {str(e)}"
            }

        # components for embeddings
        embedder_client = component_manager.get_embedder()
        rag_db = component_manager.get_rag_connector()
        deadend_agent.set_approval_callback(approval_callback)
        deadend_agent.target = target
        deadend_agent_refs.update({str(agent_id): deadend_agent})

        try:
            deadend_agent.prepare_dependencies(
                embedder_client=embedder_client,
                rag_connector=rag_db,
                sandbox=sandbox,
                target=target,
            )
        except Exception as e:
            logger.error("Failed to prepare dependencies: %s", e)
            # Clean up the agent reference if preparation fails
            deadend_agent_refs.pop(str(agent_id), None)
            return {
                "status": "failed",
                "reason": f"Failed to prepare agent dependencies: {str(e)}"
            }

        return {
            "status": "ok", 
            "agent_id": str(agent_id)
        }

    @server.add_method("embed_target")
    async def embed_target(
        _request_id: Any,
        params: Dict[str, Any],
        component_manager: ComponentManager,
        deadend_agent_refs: Dict[str, DeadEndAgent]
    ):
        target = params.get("target")
        if not target:
            yield {
                "status": "failed",
                "reason": "Must supply a target"
            }
            return
        agent_id = params.get("agent_id")
        if not agent_id:
            yield {
                "status": "failed",
                "reason": "Must supply an agent_id"
            }
            return
        agent = deadend_agent_refs.get(agent_id)
        if agent is None:
            yield {
                "phase": "error",
                "data": {
                    "message": f"Agent with id {agent_id} not found",
                    "error_type": "ValueError",
                },
            }
            return

        # components for embeddings
        embedder_client = component_manager.get_embedder()
        rag_db = component_manager.get_rag_connector()
        config = component_manager.config
        agent.init_webtarget_indexer(
            target=target
        )
        yield {
                "phase": "init",
                "data": {"message": "Crawling target..."},
        }
        await agent.crawl_target()

        yield {
                "phase": "init",
                "data": {"message": "Embedding target code..."},
        }
        code_chunks, embed_diff = await agent.embed_target(embedder_client)
        if embed_diff:
            changed = len(embed_diff.get("changed_files", []))
            removed = len(embed_diff.get("removed_files", []))
            yield {
                "phase": "init",
                "data": {"message": f"Embedding diff: changed={changed} removed={removed}"},
            }
        if rag_db is not None:
            if embed_diff:
                delete_files = embed_diff.get("changed_files", []) + embed_diff.get("removed_files", [])
                if delete_files:
                    await rag_db.delete_code_chunks_for_files(
                        session_id=agent.embedding_session_id,
                        files=delete_files
                    )
            await rag_db.batch_insert_code_chunks(code_chunks_data=code_chunks)

            yield {
                    "phase": "init",
                    "data": {"message": "Storing embeddings in database..."},
            }
        
        # Yield final completion message with "done" phase to signal stream end
        yield {
            "phase": "done",
            "data": {"message": "Target embedding completed successfully"},
        }

    @server.add_method("run_agent_recursive")
    async def run_agent_recursive(
        _request_id: Any,
        params: Dict[str, Any],
        deadend_agent_refs: Dict[str, DeadEndAgent]
    ):
        try:
            # Validate parameters first before yielding any phase
            agent_id = params.get("agent_id")
            if not agent_id:
                yield {
                    "phase": "error",
                    "data": {
                        "message": "Must supply an agent_id",
                        "error_type": "ValueError",
                    },
                }
                return

            prompt = params.get("prompt")
            if not prompt:
                yield {
                    "phase": "error",
                    "data": {
                        "message": "No prompt supplied",
                        "error_type": "ValueError",
                    },
                }
                return

            deadend_agent = deadend_agent_refs.get(agent_id)
            if deadend_agent is None:
                yield {
                    "phase": "error",
                    "data": {
                        "message": f"Agent with id {agent_id} not found",
                        "error_type": "ValueError",
                    },
                }
                return

            # Now start the recon phase
            yield {
                "phase": "recon",
                "data": {"message": "Starting web app analysis and research"},
            }
            threat_model_text = ""

            async for item in deadend_agent.threat_model_stream(task=prompt):
                threat_model_text += object_to_string(item)
                yield {
                    "phase": "recon",
                    "data": TypeAdapter(dict).dump_json(item),
                }

            yield {
                "phase": "exploit",
                "data": {"message": "Starting testing and exploit"},
            }

            async for item in deadend_agent.start_testing_stream(
                task=prompt,
                threat_model=threat_model_text
            ):
                yield {
                    "phase": "exploit",
                    "data": TypeAdapter(dict).dump_json(item),
                }
        except Exception as exc:
            logger.exception("Error in run_agent_recursive: %s", exc)
            yield {
                "phase": "error",
                "data": {
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            }
            raise

    @server.add_method("run_agent_supervisor")
    async def run_agent_supervisor(

    ):
        pass

    @server.add_method("run_agent_ask")
    async def run_agent_ask(

    ):
        pass


    server.serve()


def to_serializable(obj: Any) -> Any:
    """Convert an object to a JSON-serializable format."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_serializable(v) for v in obj]
    elif hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif is_dataclass(obj):
        return asdict(obj)
    else:
        return repr(obj)

def object_to_string(obj: Any) -> str:
    """Convert an object to a string representation for text concatenation."""
    str_obj = ""
    if hasattr(obj, "model_dump"):
        str_obj = json.dumps(obj.model_dump(), default=str)
    else:
        str_obj = str(obj)
    return str_obj

if __name__ == "__main__":
    typer.run(main)
