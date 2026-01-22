# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

""" JsonRPC server interface """
import typer
from typing import Any, Dict

from deadend_agent import DeadEndAgent, Sandbox
from deadend_agent.utils.network import check_target_alive
from deadend_cli.logging import logger
from deadend_cli.component_manager import ComponentManager
from deadend_cli.jsonrpc.rpc_server import RPCServer


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
    component_manager = ComponentManager()

    server = RPCServer(
        debug=debug,
        log_file=log_file
    )

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
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle shutdown request."""
        # self._shutdown_requested = True
        result = await component_manager.shutdown()
        return {"status": "shutdown", "components": result}

    @server.add_method("init_all")
    async def init_all(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize all components in the correct order."""
        logger.info("Starting initialization of all components...")
        result = await component_manager.init_all()
        return result.model_dump()

    @server.add_method("init_docker")
    async def init_docker(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize Docker component."""
        result = await component_manager.init_docker()
        return result.model_dump()

    @server.add_method("init_pgvector")
    async def init_pgvector(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize pgvector database."""
        result = await component_manager.init_pgvector()
        return result.model_dump()

    @server.add_method("init_config")
    async def init_config(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize configuration."""
        result = await component_manager.init_config()
        return result.model_dump()

    @server.add_method("init_model_registry")
    async def _handle_init_model_registry(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize model registry."""
        result = await component_manager.init_model_registry()
        return result.model_dump()

    @server.add_method("init_python_sandbox")
    async def _handle_init_python_sandbox(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize Python sandbox."""
        result = await component_manager.init_python_sandbox()
        return result.model_dump()

    @server.add_method("init_shell_sandbox")
    async def init_shell_sandbox(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize shell sandbox."""
        result = await component_manager.init_shell_sandbox()
        return result.model_dump()


    @server.add_method("init_playwright")
    async def init_playwright(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize Playwright browser."""
        result = await component_manager.init_playwright()
        return result.model_dump()

    @server.add_method("health_docker")
    async def health_docker(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check Docker health."""
        result = await component_manager.health_docker()
        return result.model_dump()

    @server.add_method("health_pgvector")
    async def health_pgvector(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check pgvector health."""
        result = await component_manager.health_pgvector()
        return result.model_dump()

    @server.add_method("health_python_sandbox")
    async def health_python_sandbox(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check Python sandbox health."""
        result = await component_manager.health_python_sandbox()
        return result.model_dump()

    @server.add_method("health_shell_sandbox")
    async def health_shell_sandbox(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check shell sandbox health."""
        result = await component_manager.health_shell_sandbox()
        return result.model_dump()

    @server.add_method("health_playwright")
    async def health_playwright(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check Playwright health."""
        result = await component_manager.health_playwright()
        return result.model_dump()

    @server.add_method("health_all")
    async def health_all(
        _request_id: Any,
        _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check all components health."""
        result = await component_manager.health_all()
        return result.model_dump()


    server.serve()

if __name__ == "__main__":
    typer.run(main)