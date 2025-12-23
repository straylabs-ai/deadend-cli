# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""JSON-RPC server over stdio for communicating with other front-end components."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

from deadend_agent import (
    Config,
    DeadEndAgent,
    ModelRegistry,
    RetrievalDatabaseConnector,
    Sandbox,
    init_rag_database,
    sandbox_setup,
)
from deadend_agent.utils.network import check_target_alive


class RPCServer:
    def __init__(
        self,
        config: Optional[Config] = None,
        llm_provider: str = "openai",
    ) -> None:
        self.config = config or Config()
        self.config.configure()
        self.llm_provider = llm_provider

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
        asyncio.run(self._serve_loop())

    async def _serve_loop(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue

            async for response in self._handle_request_stream(request):
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

    async def _handle_request_stream(
        self,
        request: Dict[str, Any],
    ):
        jsonrpc = request.get("jsonrpc")
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if jsonrpc != "2.0":
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid JSON-RPC version",
                },
            }
            return

        if method == "ping":
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"status": "ok"},
            }
            return

        if method != "run_task":
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}",
                },
            }
            return

        try:
            async for event in self._run_task_stream(**params):
                yield {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": event,
                }
        except Exception as exc:
            yield {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                },
            }

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
