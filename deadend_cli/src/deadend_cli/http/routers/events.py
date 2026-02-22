# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Event streaming, interrupt, and approval endpoints."""

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from deadend_agent.tools.tool_wrappers import (
    disable_approval_mode,
    enable_approval_mode,
    is_approval_mode_enabled,
)

from deadend_cli.jsonrpc.event_bus import EventBus

from ..deps import get_event_bus
from ..schemas import ApprovalModeResponse, ApprovalRequest, ApprovalResponse, InterruptRequest, InterruptResponse

router = APIRouter(prefix="/events", tags=["events"])


def _sse_message(data: dict) -> str:
    """Format a dict as a single SSE data message."""
    return f"data: {json.dumps(data)}\n\n"


async def _event_stream(event_bus: EventBus) -> AsyncGenerator[str, None]:
    """Stream events as Server-Sent Events."""
    async for event in event_bus.subscribe():
        yield _sse_message(event.model_dump())


@router.get("/stream")
async def subscribe_events(event_bus: EventBus = Depends(get_event_bus)):
    """Subscribe to agent/tool events (Server-Sent Events)."""
    return StreamingResponse(
        _event_stream(event_bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/interrupt", response_model=InterruptResponse)
async def interrupt(
    body: InterruptRequest,
    event_bus: EventBus = Depends(get_event_bus),
) -> InterruptResponse:
    """Interrupt a running session."""
    event_bus.interrupt_session(body.session_id, body.reason)
    return InterruptResponse(status="interrupted", session_id=body.session_id)


@router.post("/approve", response_model=ApprovalResponse)
async def approve(
    body: ApprovalRequest,
    event_bus: EventBus = Depends(get_event_bus),
) -> ApprovalResponse:
    """Respond to an approval request (approve or reject)."""
    success = event_bus.respond_to_approval(
        request_id=body.request_id,
        approved=body.approved,
        modified_args=body.modified_args,
    )
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Approval request {body.request_id} not found or already processed",
        )
    return ApprovalResponse(
        status="approved" if body.approved else "rejected",
        request_id=body.request_id,
    )


@router.post("/approval-mode/enable")
async def enable_approval(event_bus: EventBus = Depends(get_event_bus)):
    """Enable approval mode: all tool calls require user approval."""
    enable_approval_mode()
    return {"status": "enabled", "approval_mode": True}


@router.post("/approval-mode/disable")
async def disable_approval():
    """Disable approval mode: tools execute without approval."""
    disable_approval_mode()
    return {"status": "disabled", "approval_mode": False}


@router.get("/approval-mode", response_model=ApprovalModeResponse)
async def get_approval_mode():
    """Get current approval mode status."""
    return ApprovalModeResponse(approval_mode=is_approval_mode_enabled())
