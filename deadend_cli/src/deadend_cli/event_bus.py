# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Async event bus for streaming agent/tool events to frontend."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Awaitable, Optional

from .rpc_models import AgentEvent, EventType


class PendingApproval:
    """Tracks a pending approval request."""

    def __init__(
        self,
        request_id: str,
        session_id: str,
        agent_name: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ):
        self.request_id = request_id
        self.session_id = session_id
        self.agent_name = agent_name
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.created_at = datetime.now()
        self.response_event = asyncio.Event()
        self.approved: bool = False
        self.modified_args: Optional[dict[str, Any]] = None


class EventBus:
    """Async event bus for agent/tool events.

    Provides non-blocking event publishing and async subscription.
    Also manages pending approval requests for the approval workflow.
    """

    def __init__(self, max_queue_size: int = 1000):
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._pending_approvals: dict[str, PendingApproval] = {}
        self._interrupted_sessions: set[str] = set()
        self._subscribers: list[Callable[[AgentEvent], Awaitable[None]]] = []

    async def publish(self, event: AgentEvent) -> None:
        """Publish an event to the queue (non-blocking, drops if full)."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop event to avoid blocking agents

    def publish_sync(self, event: AgentEvent) -> None:
        """Synchronous publish - schedules async publish as task."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # No event loop running, try direct put
            try:
                self._queue.put_nowait(event)
            except (asyncio.QueueFull, RuntimeError):
                pass

    async def subscribe(self) -> AsyncGenerator[AgentEvent, None]:
        """Async generator for consuming events."""
        while True:
            event = await self._queue.get()
            yield event
            self._queue.task_done()

    def subscribe_callback(self, callback: Callable[[AgentEvent], Awaitable[None]]) -> None:
        """Register a callback to be invoked for each event."""
        self._subscribers.append(callback)

    def unsubscribe_callback(self, callback: Callable[[AgentEvent], Awaitable[None]]) -> None:
        """Unregister a callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ==========================================================================
    # Convenience emit methods
    # ==========================================================================

    def emit_agent_start(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        task_id: Optional[str] = None,
        depth: int = 0,
        parent_task_id: Optional[str] = None,
    ) -> None:
        """Emit an AGENT_START event."""
        event = AgentEvent.agent_start(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            task_id=task_id,
            depth=depth,
            parent_task_id=parent_task_id,
        )
        self.publish_sync(event)

    def emit_agent_end(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        confidence_score: float,
        task_id: Optional[str] = None,
        notes: Optional[str] = None,
        thought_summary: Optional[str] = None,
        attempts: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Emit an AGENT_END event."""
        event = AgentEvent.agent_end(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            confidence_score=confidence_score,
            task_id=task_id,
            notes=notes,
            thought_summary=thought_summary,
            attempts=attempts,
        )
        self.publish_sync(event)

    def emit_agent_error(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        error_type: str,
        error_message: str,
        task_id: Optional[str] = None,
        partial_reasoning: Optional[str] = None,
    ) -> None:
        """Emit an AGENT_ERROR event."""
        event = AgentEvent.agent_error(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            error_type=error_type,
            error_message=error_message,
            task_id=task_id,
            partial_reasoning=partial_reasoning,
        )
        self.publish_sync(event)

    def emit_agent_thought(
        self,
        session_id: str,
        agent_name: str,
        thought: str,
        summary: Optional[str] = None,
        relevance: float = 0.5,
    ) -> None:
        """Emit an AGENT_THOUGHT event."""
        event = AgentEvent.agent_thought(
            session_id=session_id,
            agent_name=agent_name,
            thought=thought,
            summary=summary,
            relevance=relevance,
        )
        self.publish_sync(event)

    def emit_agent_routed(
        self,
        session_id: str,
        task: str,
        selected_agent: str,
        reasoning: str,
        available_agents: Optional[list[str]] = None,
    ) -> None:
        """Emit an AGENT_ROUTED event."""
        event = AgentEvent.agent_routed(
            session_id=session_id,
            task=task,
            selected_agent=selected_agent,
            reasoning=reasoning,
            available_agents=available_agents,
        )
        self.publish_sync(event)

    def emit_tool_call_start(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        args: str = "",
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Emit a TOOL_CALL_START event."""
        event = AgentEvent.tool_call_start(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            args=args,
            tool_call_id=tool_call_id,
        )
        self.publish_sync(event)

    def emit_tool_call_end(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        success: bool,
        result: str = "",
        error: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Emit a TOOL_CALL_END event."""
        event = AgentEvent.tool_call_end(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            success=success,
            result=result,
            error=error,
            tool_call_id=tool_call_id,
            duration_ms=duration_ms,
        )
        self.publish_sync(event)

    def emit_task_expanded(
        self,
        session_id: str,
        parent_task: str,
        parent_task_id: str,
        subtasks: list[dict[str, Any]],
    ) -> None:
        """Emit a TASK_EXPANDED event."""
        event = AgentEvent.task_expanded(
            session_id=session_id,
            parent_task=parent_task,
            parent_task_id=parent_task_id,
            subtasks=subtasks,
        )
        self.publish_sync(event)

    def emit_confidence_update(
        self,
        session_id: str,
        task: str,
        task_id: str,
        old_confidence: float,
        new_confidence: float,
        decision: str,
    ) -> None:
        """Emit a CONFIDENCE_UPDATE event."""
        event = AgentEvent.confidence_update(
            session_id=session_id,
            task=task,
            task_id=task_id,
            old_confidence=old_confidence,
            new_confidence=new_confidence,
            decision=decision,
        )
        self.publish_sync(event)

    def emit_validation_result(
        self,
        session_id: str,
        task: str,
        task_id: str,
        valid: bool,
        confidence_score: float,
        critique: str,
        validation_token: Optional[str] = None,
    ) -> None:
        """Emit a VALIDATION_RESULT event."""
        event = AgentEvent.validation_result(
            session_id=session_id,
            task=task,
            task_id=task_id,
            valid=valid,
            confidence_score=confidence_score,
            critique=critique,
            validation_token=validation_token,
        )
        self.publish_sync(event)

    def emit_log_message(
        self,
        session_id: str,
        message: str,
        level: str = "info",
        source: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> None:
        """Emit a LOG_MESSAGE event."""
        event = AgentEvent.log_message(
            session_id=session_id,
            message=message,
            level=level,
            source=source,
            agent_name=agent_name,
        )
        self.publish_sync(event)

    # ==========================================================================
    # Approval workflow
    # ==========================================================================

    async def request_approval(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        tool_args: dict[str, Any],
        description: str,
        timeout: float = 300.0,  # 5 minutes default timeout
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        """Request user approval for a tool call.

        Emits APPROVAL_REQUIRED event and waits for response.

        Args:
            session_id: Current session ID
            agent_name: Name of the agent requesting approval
            tool_name: Name of the tool to be executed
            tool_args: Arguments for the tool
            description: Human-readable description of the action
            timeout: Timeout in seconds to wait for approval

        Returns:
            Tuple of (approved: bool, modified_args: Optional[dict])
        """
        request_id = str(uuid.uuid4())

        pending = PendingApproval(
            request_id=request_id,
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        self._pending_approvals[request_id] = pending

        # Emit approval required event
        event = AgentEvent.approval_required(
            session_id=session_id,
            agent_name=agent_name,
            request_id=request_id,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
        )
        await self.publish(event)

        # Wait for response
        try:
            await asyncio.wait_for(pending.response_event.wait(), timeout=timeout)
            return pending.approved, pending.modified_args
        except asyncio.TimeoutError:
            return False, None
        finally:
            self._pending_approvals.pop(request_id, None)

    def respond_to_approval(
        self,
        request_id: str,
        approved: bool,
        modified_args: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Respond to a pending approval request.

        Args:
            request_id: The approval request ID
            approved: Whether the request is approved
            modified_args: Optional modified arguments

        Returns:
            True if the approval was found and processed, False otherwise
        """
        pending = self._pending_approvals.get(request_id)
        if pending is None:
            return False

        pending.approved = approved
        pending.modified_args = modified_args
        pending.response_event.set()
        return True

    def get_pending_approvals(self, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Get list of pending approval requests.

        Args:
            session_id: Optional session ID to filter by

        Returns:
            List of pending approval details
        """
        approvals = []
        for req_id, pending in self._pending_approvals.items():
            if session_id is None or pending.session_id == session_id:
                approvals.append({
                    "request_id": req_id,
                    "session_id": pending.session_id,
                    "agent_name": pending.agent_name,
                    "tool_name": pending.tool_name,
                    "tool_args": pending.tool_args,
                    "created_at": pending.created_at.isoformat(),
                })
        return approvals

    # ==========================================================================
    # Interruption workflow
    # ==========================================================================

    def interrupt_session(self, session_id: str, reason: str = "User requested interruption") -> None:
        """Mark a session as interrupted.

        Args:
            session_id: The session to interrupt
            reason: Reason for interruption
        """
        self._interrupted_sessions.add(session_id)
        event = AgentEvent.workflow_interrupted(
            session_id=session_id,
            reason=reason,
        )
        self.publish_sync(event)

    def is_interrupted(self, session_id: str) -> bool:
        """Check if a session has been interrupted."""
        return session_id in self._interrupted_sessions

    def clear_interruption(self, session_id: str) -> None:
        """Clear the interruption flag for a session."""
        self._interrupted_sessions.discard(session_id)

    # ==========================================================================
    # Utility methods
    # ==========================================================================

    def clear_queue(self) -> int:
        """Clear all pending events from the queue.

        Returns:
            Number of events cleared
        """
        count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break
        return count

    @property
    def queue_size(self) -> int:
        """Current number of events in the queue."""
        return self._queue.qsize()


# Global event bus instance
event_bus = EventBus()


__all__ = [
    "EventBus",
    "PendingApproval",
    "event_bus",
]
