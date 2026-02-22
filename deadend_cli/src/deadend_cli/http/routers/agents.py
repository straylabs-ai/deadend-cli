# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent and task endpoints: instantiate, embed, run."""

import json
import uuid
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from deadend_agent import DeadEndAgent
from deadend_agent.utils.network import deterministic_session_id

from deadend_cli.cli_logging import logger
from deadend_cli.component_manager import ComponentManager

from ..deps import get_agent_refs, get_component_manager, get_event_bus
from ..schemas import (
    EmbedTargetRequest,
    InstantiateAgentRequest,
    InstantiateAgentResponse,
    RunAgentRequest,
)


def _to_serializable(obj: Any) -> Any:
    """Convert to JSON-serializable form for streaming."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def _sse_message(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


router = APIRouter(prefix="/agents", tags=["agents"])

AVAILABLE_AGENTS = {
    "requester": (
        "Agent specialized in fine-grained testing and sending raw request data. "
        "Best for gathering auth tokens, testing individual endpoints, and precise request manipulation."
    ),
    "python_interpreter": (
        "Agent specialized in generating code and running it safely in a sandbox. "
        "Best for fuzzing, parameter testing, and repetitive security testing operations."
    ),
    "shell": "Agent providing access to a bash shell for running Linux commands.",
    "router_agent": "Router agent that selects the appropriate specialized agent.",
    "webapp_analyzer": (
        "Front-end webapp analyzer. This agent is specialized in looking into the web application "
        "to extract information about the logic details of the application."
    ),
}


@router.post("", response_model=InstantiateAgentResponse)
async def instantiate_agent(
    body: InstantiateAgentRequest,
    component_manager: ComponentManager = Depends(get_component_manager),
    deadend_agent_refs: Dict[str, DeadEndAgent] = Depends(get_agent_refs),
) -> InstantiateAgentResponse:
    """Create and prepare an agent for a target. Returns agent_id for use in embed and run."""
    if not body.target:
        return InstantiateAgentResponse(status="failed", reason="Must supply a target")

    try:
        model = component_manager.get_model(provider=body.provider, model_name=body.model_name)
    except (RuntimeError, ValueError) as e:
        return InstantiateAgentResponse(status="failed", reason=str(e))

    agent_id = uuid.uuid4()
    runtime_session_id = uuid.uuid4()
    embedding_session_id = deterministic_session_id(body.target)

    deadend_agent = DeadEndAgent(
        session_id=runtime_session_id,
        embedding_session_id=embedding_session_id,
        model=model,
        available_agents=AVAILABLE_AGENTS,
        max_depth=3,
    )

    async def approval_callback() -> str:
        return "yes"

    try:
        sandbox = component_manager.create_task_sandbox()
    except Exception as e:
        logger.error("Failed to create sandbox: %s", e)
        return InstantiateAgentResponse(status="failed", reason=f"Failed to create sandbox: {str(e)}")

    embedder_client = component_manager.get_embedder()
    rag_db = component_manager.get_rag_connector()
    deadend_agent.set_approval_callback(approval_callback)
    deadend_agent.target = body.target
    deadend_agent_refs[str(agent_id)] = deadend_agent

    try:
        deadend_agent.prepare_dependencies(
            embedder_client=embedder_client,
            rag_connector=rag_db,
            sandbox=sandbox,
            target=body.target,
        )
    except Exception as e:
        logger.error("Failed to prepare dependencies: %s", e)
        deadend_agent_refs.pop(str(agent_id), None)
        return InstantiateAgentResponse(status="failed", reason=f"Failed to prepare agent dependencies: {str(e)}")

    return InstantiateAgentResponse(status="ok", agent_id=str(agent_id))


async def _embed_target_stream(
    agent_id: str,
    target: str,
    component_manager: ComponentManager,
    deadend_agent_refs: Dict[str, DeadEndAgent],
) -> AsyncGenerator[str, None]:
    """Stream embed phases as SSE."""
    agent = deadend_agent_refs.get(agent_id)
    if agent is None:
        yield _sse_message({"phase": "error", "data": {"message": f"Agent {agent_id} not found", "error_type": "ValueError"}})
        return

    embedder_client = component_manager.get_embedder()
    rag_db = component_manager.get_rag_connector()
    agent.init_webtarget_indexer(target=target)

    yield _sse_message({"phase": "init", "data": {"message": "Crawling target..."}})
    await agent.crawl_target()

    yield _sse_message({"phase": "init", "data": {"message": "Embedding target code..."}})
    code_chunks, embed_diff = await agent.embed_target(embedder_client)
    if embed_diff:
        changed = len(embed_diff.get("changed_files", []))
        removed = len(embed_diff.get("removed_files", []))
        yield _sse_message({"phase": "init", "data": {"message": f"Embedding diff: changed={changed} removed={removed}"}})

    if rag_db is not None:
        if embed_diff:
            delete_files = embed_diff.get("changed_files", []) + embed_diff.get("removed_files", [])
            if delete_files:
                await rag_db.delete_code_chunks_for_files(session_id=agent.embedding_session_id, files=delete_files)
        await rag_db.batch_insert_code_chunks(code_chunks_data=code_chunks)
        yield _sse_message({"phase": "init", "data": {"message": "Storing embeddings in database..."}})

    yield _sse_message({"phase": "done", "data": {"message": "Target embedding completed successfully"}})


@router.post("/embed")
async def embed_target(
    body: EmbedTargetRequest,
    component_manager: ComponentManager = Depends(get_component_manager),
    deadend_agent_refs: Dict[str, DeadEndAgent] = Depends(get_agent_refs),
):
    """Embed a target for an agent (streaming). Requires agent_id from instantiate_agent."""
    if not body.agent_id:
        raise HTTPException(status_code=400, detail="Must supply agent_id")
    target = body.target
    agent = deadend_agent_refs.get(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {body.agent_id} not found")
    if not target:
        target = agent.target
    if not target:
        raise HTTPException(status_code=400, detail="Must supply target or use an agent that has a target")

    return StreamingResponse(
        _embed_target_stream(body.agent_id, target, component_manager, deadend_agent_refs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _run_agent_recursive_stream(
    agent_id: str,
    prompt: str,
    deadend_agent_refs: Dict[str, DeadEndAgent],
) -> AsyncGenerator[str, None]:
    """Stream recon + exploit phases as SSE."""
    try:
        agent = deadend_agent_refs.get(agent_id)
        if agent is None:
            yield _sse_message({"phase": "error", "data": {"message": f"Agent {agent_id} not found", "error_type": "ValueError"}})
            return

        yield _sse_message({"phase": "recon", "data": {"message": "Starting web app analysis and research"}})
        threat_model_text = ""

        async for item in agent.threat_model_stream(task=prompt):
            threat_model_text += json.dumps(_to_serializable(item), default=str)
            yield _sse_message({"phase": "recon", "data": _to_serializable(item)})

        yield _sse_message({"phase": "exploit", "data": {"message": "Starting testing and exploit"}})
        async for item in agent.start_testing_stream(task=prompt, threat_model=threat_model_text):
            yield _sse_message({"phase": "exploit", "data": _to_serializable(item)})
    except Exception as exc:
        logger.exception("Error in run_agent_recursive: %s", exc)
        yield _sse_message({"phase": "error", "data": {"message": str(exc), "error_type": type(exc).__name__}})


@router.post("/run/recursive")
async def run_agent_recursive(
    body: RunAgentRequest,
    deadend_agent_refs: Dict[str, DeadEndAgent] = Depends(get_agent_refs),
):
    """Run agent in recursive mode: recon then exploit (streaming)."""
    if not body.agent_id:
        raise HTTPException(status_code=400, detail="Must supply agent_id")
    if not body.prompt:
        raise HTTPException(status_code=400, detail="No prompt supplied")

    return StreamingResponse(
        _run_agent_recursive_stream(body.agent_id, body.prompt, deadend_agent_refs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _run_agent_supervisor_stream(
    agent_id: str,
    prompt: str,
    deadend_agent_refs: Dict[str, DeadEndAgent],
) -> AsyncGenerator[str, None]:
    """Stream supervisor phase as SSE."""
    try:
        agent = deadend_agent_refs.get(agent_id)
        if agent is None:
            yield _sse_message({"phase": "error", "data": {"message": f"Agent {agent_id} not found", "error_type": "ValueError"}})
            return

        yield _sse_message({"phase": "supervising", "data": {"message": "looking and testing..."}})
        async for item in agent.start_supervisor(task=prompt):
            yield _sse_message({"phase": "recon", "data": _to_serializable(item)})
    except Exception as exc:
        logger.exception("Error in run_agent_supervisor: %s", exc)
        yield _sse_message({"phase": "error", "data": {"message": str(exc), "error_type": type(exc).__name__}})


@router.post("/run/supervisor")
async def run_agent_supervisor(
    body: RunAgentRequest,
    deadend_agent_refs: Dict[str, DeadEndAgent] = Depends(get_agent_refs),
):
    """Run agent in supervisor mode (streaming)."""
    if not body.agent_id:
        raise HTTPException(status_code=400, detail="Must supply agent_id")
    if not body.prompt:
        raise HTTPException(status_code=400, detail="No prompt supplied")

    return StreamingResponse(
        _run_agent_supervisor_stream(body.agent_id, body.prompt, deadend_agent_refs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
