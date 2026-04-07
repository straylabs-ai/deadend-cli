# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

""" JsonRPC server interface """
from typing import Any, Dict, AsyncGenerator
import json
from pathlib import Path
from importlib.resources import files
import shutil
import os
from dataclasses import asdict, dataclass, field, is_dataclass
from pydantic import TypeAdapter
import typer
import uuid
from deadend_agent import DeadEndAgent, Sandbox, config_setup, set_event_hooks
from deadend_agent.agents.factory import FallbackAgentResult
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


@dataclass
class TrackedTask:
    task_id: str
    task: str
    status: str
    depth: int
    parent_task_id: str | None = None
    confidence_score: float | None = None
    updated_index: int = 0


@dataclass
class AgentTaskSnapshot:
    agent_id: str
    session_id: str
    target: str | None = None
    root_task_id: str | None = None
    current_task_id: str | None = None
    tasks: dict[str, TrackedTask] = field(default_factory=dict)
    update_index: int = 0


class TaskRegistry:
    """Keeps a live task snapshot per RPC agent for frontend polling."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentTaskSnapshot] = {}
        self._session_to_agent: dict[str, str] = {}

    def register_agent(self, agent_id: str, session_id: str, target: str | None = None) -> None:
        self._session_to_agent[session_id] = agent_id
        self._agents[agent_id] = AgentTaskSnapshot(
            agent_id=agent_id,
            session_id=session_id,
            target=target,
        )

    def unregister_agent(self, agent_id: str) -> None:
        snapshot = self._agents.pop(agent_id, None)
        if snapshot is not None:
            self._session_to_agent.pop(snapshot.session_id, None)

    def reset_agent(self, agent_id: str) -> None:
        snapshot = self._agents.get(agent_id)
        if snapshot is None:
            return
        snapshot.root_task_id = None
        snapshot.current_task_id = None
        snapshot.tasks = {}
        snapshot.update_index = 0

    async def handle_event(self, event: Any) -> None:
        session_id = str(getattr(event, "session_id", ""))
        agent_id = self._session_to_agent.get(session_id)
        if not agent_id:
            return

        event_type = getattr(getattr(event, "type", None), "value", getattr(event, "type", None))
        data = getattr(event, "data", None)
        if data is None:
            return

        if event_type == "task_created":
            self.record_task_created(
                agent_id=agent_id,
                task_id=str(getattr(data, "task_id")),
                task=str(getattr(data, "task")),
                depth=int(getattr(data, "depth")),
                parent_task_id=getattr(data, "parent_task_id", None),
                initial_confidence=float(getattr(data, "initial_confidence", 0.0)),
            )
        elif event_type == "task_status_changed":
            self.record_task_status_changed(
                agent_id=agent_id,
                task_id=str(getattr(data, "task_id")),
                task=str(getattr(data, "task")),
                old_status=str(getattr(data, "old_status")),
                new_status=str(getattr(data, "new_status")),
                confidence_score=getattr(data, "confidence_score", None),
            )
        elif event_type == "task_expanded":
            for subtask in list(getattr(data, "subtasks", []) or []):
                if not isinstance(subtask, dict):
                    continue
                parent_task_id = subtask.get("parent_task_id")
                if parent_task_id is None:
                    parent_task_id = getattr(data, "parent_task_id", None)
                self.record_task_created(
                    agent_id=agent_id,
                    task_id=str(subtask.get("task_id")),
                    task=str(subtask.get("task")),
                    depth=int(subtask.get("depth", 0)),
                    parent_task_id=None if parent_task_id is None else str(parent_task_id),
                    initial_confidence=float(subtask.get("confidence_score", 0.0) or 0.0),
                )

    def record_task_created(
        self,
        agent_id: str,
        task_id: str,
        task: str,
        depth: int,
        parent_task_id: str | None = None,
        initial_confidence: float | None = None,
    ) -> None:
        snapshot = self._agents.get(agent_id)
        if snapshot is None:
            return

        snapshot.update_index += 1
        existing = snapshot.tasks.get(task_id)
        status = existing.status if existing is not None else "pending"
        confidence_score = existing.confidence_score if existing is not None else initial_confidence
        snapshot.tasks[task_id] = TrackedTask(
            task_id=task_id,
            task=task,
            status=status,
            depth=depth,
            parent_task_id=parent_task_id,
            confidence_score=confidence_score,
            updated_index=snapshot.update_index,
        )
        if depth == 0 and snapshot.root_task_id is None:
            snapshot.root_task_id = task_id

    def record_task_status_changed(
        self,
        agent_id: str,
        task_id: str,
        task: str,
        old_status: str,
        new_status: str,
        confidence_score: float | None = None,
    ) -> None:
        del old_status
        snapshot = self._agents.get(agent_id)
        if snapshot is None:
            return

        existing = snapshot.tasks.get(task_id)
        if existing is None:
            self.record_task_created(
                agent_id=agent_id,
                task_id=task_id,
                task=task,
                depth=0,
                parent_task_id=None,
                initial_confidence=confidence_score,
            )
            existing = snapshot.tasks.get(task_id)
            if existing is None:
                return

        snapshot.update_index += 1
        existing.task = task
        existing.status = new_status
        if confidence_score is not None:
            existing.confidence_score = float(confidence_score)
        existing.updated_index = snapshot.update_index

        if new_status == "in_progress":
            snapshot.current_task_id = task_id
        elif snapshot.current_task_id == task_id and new_status != "in_progress":
            in_progress = [
                candidate for candidate in snapshot.tasks.values()
                if candidate.status == "in_progress"
            ]
            snapshot.current_task_id = (
                max(in_progress, key=lambda item: item.updated_index).task_id
                if in_progress else None
            )

    def get_snapshot(self, agent_id: str) -> dict[str, Any] | None:
        snapshot = self._agents.get(agent_id)
        if snapshot is None:
            return None

        tasks = sorted(
            snapshot.tasks.values(),
            key=lambda task: (task.depth, task.updated_index, task.task_id),
        )
        return {
            "agent_id": snapshot.agent_id,
            "session_id": snapshot.session_id,
            "target": snapshot.target,
            "root_task_id": snapshot.root_task_id,
            "current_task_id": snapshot.current_task_id,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "parent_task_id": task.parent_task_id,
                    "task": task.task,
                    "status": task.status,
                    "depth": task.depth,
                    "confidence_score": task.confidence_score,
                    "is_current": task.task_id == snapshot.current_task_id,
                }
                for task in tasks
            ],
        }


def _phoenix_otel_enabled() -> bool:
    """True if Phoenix OTLP should be used (from .env / env vars)."""
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "").strip()
    enabled = os.getenv("DEADEND_PHOENIX_OTEL_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return bool(endpoint) or enabled
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
    task_registry = TaskRegistry()
    event_bus.subscribe_callback(task_registry.handle_event)
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
    # reusable creds 
    # copy reusable creds to cache
    try:
        source_creds = files("deadend_cli").joinpath("data", "memory", "reusable_credentials.json")
        path_creds = Path(str(source_creds))

    except (ImportError, FileNotFoundError):
        print("not found.")
        path_creds = Path(__file__) / "data" / "memory" / "reusable_credentials.json"
    cache_dir = Path.home() / ".cache" / "deadend" / "memory"
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination_file = cache_dir / "reusable_credentials.json"
    if path_creds.exists():
        shutil.copy2(path_creds, destination_file)
    # setting up tracing
    if _phoenix_otel_enabled():
        # Register Phoenix OTLP before importing the agent so the global tracer provider
        # is Phoenix; agent telemetry will then use it (see DEADEND_OTEL_USE_GLOBAL in telemetry.py).
        os.environ["DEADEND_OTEL_USE_GLOBAL"] = "1"
        from phoenix.otel import register

        endpoint = (os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or "https://crunch.straylabs.ai/").strip().rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint = f"{endpoint}/v1/traces"
        project_name = os.getenv("PHOENIX_PROJECT_NAME", "deadend")

        register(
            auto_instrument=True,
            project_name=project_name,
            batch=True,
            endpoint=endpoint,
            protocol="http/protobuf",
        )

    server.add_dependency("component_manager", component_manager)
    server.add_dependency("event_bus", event_bus)
    server.add_dependency("deadend_agent_refs", deadend_agent_refs)
    server.add_dependency("task_registry", task_registry)

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

    @server.add_method("init_rag")
    async def init_rag(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Initialize SQLite-backed RAG session manager."""
        result = await component_manager.init_rag()
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

    @server.add_method("health_rag")
    async def health_rag(
        _request_id: Any,
        _params: Dict[str, Any],
        component_manager: ComponentManager
    ) -> Dict[str, Any]:
        """Check RAG (SQLite) session manager health."""
        result = await component_manager.health_rag()
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

    @server.add_method("get_agent_tasks")
    async def get_agent_tasks(
        _request_id: Any,
        params: Dict[str, Any],
        task_registry: TaskRegistry,
    ) -> Dict[str, Any]:
        agent_id = params.get("agent_id")
        if not agent_id:
            return {
                "status": "failed",
                "reason": "Must supply an agent_id",
            }

        snapshot = task_registry.get_snapshot(str(agent_id))
        if snapshot is None:
            return {
                "status": "failed",
                "reason": f"Agent with id {agent_id} not found",
            }

        return {
            "status": "ok",
            **snapshot,
        }

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
    # Validation config methods
    # ==========================================

    @server.add_method("get_validation_config")
    async def get_validation_config(
        _request_id: Any,
        params: Dict[str, Any],
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Read the current validation config from disk."""
        from deadend_agent.agents.components.validation_strategies import (
            load_validation_config,
            PRESETS,
        )

        config = load_validation_config()
        strategy_names = [s.name for s in config.strategies]

        # Detect which preset matches, if any.
        matched_preset: str | None = None
        for preset_name, preset_strategies in PRESETS.items():
            if strategy_names == preset_strategies:
                matched_preset = preset_name
                break

        return {
            "status": "ok",
            "validation_format": config.validation_format,
            "validation_type": config.validation_type,
            "strategies": [s.model_dump() for s in config.strategies],
            "preset": matched_preset,
            "available_presets": list(PRESETS.keys()),
        }

    @server.add_method("set_validation_config")
    async def set_validation_config(
        _request_id: Any,
        params: Dict[str, Any],
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        """Write a new validation config to disk.

        Accepts either a ``preset`` name (flag, judge, ctf, recon) or a full
        config with ``validation_format``, ``validation_type``, and
        ``strategies``.
        """
        import yaml as _yaml
        from deadend_agent.agents.components.validation_strategies import (
            DEFAULT_CONFIG_PATH,
            PRESETS,
            ValidationConfig,
            StrategyConfig,
        )

        preset = params.get("preset")
        if preset:
            if preset not in PRESETS:
                return {
                    "status": "failed",
                    "reason": f"Unknown preset '{preset}'. Available: {list(PRESETS.keys())}",
                }
            strategy_names = PRESETS[preset]
            v_format = params.get("validation_format")
            v_type = params.get("validation_type")
            pattern = params.get("pattern")

            strategies: list[Dict[str, Any]] = []
            for name in strategy_names:
                entry: Dict[str, Any] = {"name": name}
                if name == "flag" and pattern:
                    entry["pattern"] = pattern
                if name == "judge":
                    if v_format:
                        entry["validation_format"] = v_format
                strategies.append(entry)

            config_dict: Dict[str, Any] = {"strategies": strategies}
            if v_format is not None:
                config_dict["validation_format"] = v_format
            if v_type is not None:
                config_dict["validation_type"] = v_type
        else:
            config_dict = {
                k: v for k, v in params.items()
                if k in ("validation_format", "validation_type", "strategies")
            }

        # Validate through pydantic before writing.
        try:
            parsed = ValidationConfig(**config_dict)
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

        DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONFIG_PATH.write_text(
            _yaml.dump(parsed.model_dump(exclude_none=True), default_flow_style=False),
            encoding="utf-8",
        )

        return {
            "status": "ok",
            "validation_format": parsed.validation_format,
            "validation_type": parsed.validation_type,
            "strategies": [s.model_dump() for s in parsed.strategies],
        }

    # ==========================================
    # Agent methods methods
    # ==========================================
    @server.add_method("instantiate_agent")
    async def instantiate_agent(
        _request_id: Any,
        params: Dict[str, Any],
        component_manager: ComponentManager,
        deadend_agent_refs: Dict[str, DeadEndAgent],
        task_registry: TaskRegistry,
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
        workspace_root = params.get("workspace_root")

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
                "Agent specialized in quick targeted HTTP testing. "
                "Best default for simple requests, auth checks, individual endpoints, "
                "and lightweight payload validation."
            ),
            "python_interpreter": (
                "Agent specialized in generating code and running it safely in a sandbox. "
                "Best for fuzzing, repeated exploit attempts, sending many requests, "
                "parameter testing, and stateful security testing operations."
            ),
            "shell": (
                "Agent providing access to a bash shell for CLI tooling. "
                "Use for curl when exact request control is required and for external "
                "security tools such as ffuf, gobuster, sqlmap, or nmap."
            ),
            "memory": "Agent specialized in reading and writing the persistent memory workspace under the agent cache.",
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
            max_depth=3,
            workspace_root=workspace_root,
            agents_storage_root=component_manager.config.agents_storage_root,
            local_agent_id=component_manager.config.get_local_agent_id(),
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
        rag_manager = component_manager.get_rag_session_manager()
        local_agent_id = component_manager.config.get_local_agent_id()
        rag_db = await rag_manager.get_connector(
            agent_id=local_agent_id,
            embedding_session_id=embedding_session_id,
            target=target,
        )
        deadend_agent.set_approval_callback(approval_callback)
        deadend_agent.target = target
        deadend_agent_refs.update({str(agent_id): deadend_agent})
        task_registry.register_agent(
            agent_id=str(agent_id),
            session_id=str(runtime_session_id),
            target=target,
        )

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
            task_registry.unregister_agent(str(agent_id))
            return {
                "status": "failed",
                "reason": f"Failed to prepare agent dependencies: {str(e)}"
            }

        return {
            "status": "ok", 
            "agent_id": str(agent_id)
        }

    @server.add_method("interrupt_agent")
    async def interrupt_agent(
        _request_id: Any,
        params: Dict[str, Any],
        event_bus: EventBus,
        component_manager: ComponentManager,
        deadend_agent_refs: Dict[str, DeadEndAgent]
    ):
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
        agent.interrupt_workflow()

        yield {
            "status": "interrupted",
            "agent_id": agent_id
        }
        return

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
        rag_manager = component_manager.get_rag_session_manager()
        local_agent_id = component_manager.config.get_local_agent_id()
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

        rag_db = await rag_manager.get_connector(
            agent_id=local_agent_id,
            embedding_session_id=agent.embedding_session_id,
            target=target,
        )
        if embed_diff:
            delete_files = embed_diff.get("changed_files", []) + embed_diff.get("removed_files", [])
            if delete_files:
                await rag_db.delete_code_chunks_for_files(files=delete_files)
        if code_chunks:
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
        deadend_agent_refs: Dict[str, DeadEndAgent],
        task_registry: TaskRegistry,
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

            # Reset workflow state
            task_registry.reset_agent(str(agent_id))
            deadend_agent.reset_workflow_state()

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
                    "data": TypeAdapter(dict).dump_json(stream_item_to_dict(item)),
                }

            yield {
                "phase": "exploit",
                "data": {"message": "Starting testing and exploit"},
            }

            task_registry.reset_agent(str(agent_id))

            async for item in deadend_agent.start_testing_stream(
                task=prompt,
                threat_model=threat_model_text
            ):

                yield {
                    "phase": "exploit",
                    "data": TypeAdapter(dict).dump_json(stream_item_to_dict(item)),
                }
        except Exception as exc:
            # Log full traceback; message already includes full detail (e.g. 429 body) from core_agent
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
        _request_id: Any,
        params: Dict[str, Any],
        deadend_agent_refs: Dict[str, DeadEndAgent],
        task_registry: TaskRegistry,
    ):
        try:
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
            yield {
                "phase": "supervising",
                "data": {"message": "looking and testing..."},
            }
            supervising_text = ""
            # Reset workflow state
            task_registry.reset_agent(str(agent_id))
            deadend_agent.reset_workflow_state()
            async for item in deadend_agent.start_supervisor(task=prompt):
                supervising_text += object_to_string(item)
                yield {
                    "phase": "recon",
                    "data": TypeAdapter(dict).dump_json(stream_item_to_dict(item)),
                }

        except Exception as exc:
            logger.exception("Error in run_agent_supervisor: %s", exc)
            yield {
                "phase": "error",
                "data": {
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            }
            raise

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
    elif isinstance(obj, FallbackAgentResult):
        return {
            "error": obj.error,
            "output": to_serializable(obj.output),
            "_fallback": True,
        }
    elif hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif is_dataclass(obj):
        return asdict(obj)
    else:
        return repr(obj)


def stream_item_to_dict(item: Any) -> Dict[str, Any]:
    """Convert a streamed item (e.g. from threat_model_stream / start_supervisor) to a JSON-serializable dict.

    Handles FallbackAgentResult so the RPC response never tries to serialize that type directly.
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, FallbackAgentResult):
        return {
            "error": item.error,
            "output": to_serializable(item.output),
            "_fallback": True,
        }
    out = to_serializable(item)
    return out if isinstance(out, dict) else {"data": out}

def object_to_string(obj: Any) -> str:
    """Convert an object to a string representation for text concatenation."""
    str_obj = ""
    if hasattr(obj, "model_dump"):
        str_obj = json.dumps(obj.model_dump(), default=str)
    else:
        str_obj = str(obj)
    return str_obj

if __name__ == "__main__":
    """Entrypoint to the jsonrpc server.

    """
    typer.run(main)
