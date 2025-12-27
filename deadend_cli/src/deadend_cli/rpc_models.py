# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Pydantic models for JSON-RPC server state, responses, and agent events."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field


# =============================================================================
# Component Status Models
# =============================================================================


class ComponentStatus(str, Enum):
    """Component lifecycle states."""

    NOT_INITIALIZED = "not_initialized"
    INITIALIZING = "initializing"
    READY = "ready"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"
    ERROR = "error"


class ComponentState(BaseModel):
    """State tracking for a single component."""

    name: str
    status: ComponentStatus = ComponentStatus.NOT_INITIALIZED
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InitResult(BaseModel):
    """Result of an initialization operation."""

    success: bool
    component: str
    status: ComponentStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResult(BaseModel):
    """Result of a health check."""

    component: str
    healthy: bool
    status: ComponentStatus
    message: str
    latency_ms: Optional[float] = None
    details: dict[str, Any] = Field(default_factory=dict)


class AllHealthResult(BaseModel):
    """Combined health check result."""

    overall_healthy: bool
    components: list[HealthResult]
    timestamp: datetime = Field(default_factory=datetime.now)


# =============================================================================
# Agent/Tool Event Types
# =============================================================================


class EventType(str, Enum):
    """Types of events emitted during agent execution."""

    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # Agent reasoning/thoughts (streamed)
    AGENT_THOUGHT = "agent_thought"

    # Routing
    AGENT_ROUTED = "agent_routed"

    # Tool calls (real-time)
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"

    # Approval mechanism
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESPONSE = "approval_response"

    # Interruption
    WORKFLOW_INTERRUPTED = "workflow_interrupted"

    # Task decomposition
    TASK_CREATED = "task_created"
    TASK_EXPANDED = "task_expanded"
    TASK_STATUS_CHANGED = "task_status_changed"

    # Confidence & validation
    CONFIDENCE_UPDATE = "confidence_update"
    VALIDATION_RESULT = "validation_result"

    # Execution records
    EXECUTION_RECORD = "execution_record"
    LOG_MESSAGE = "log_message"


# =============================================================================
# Typed Event Data Models
# =============================================================================


class AgentStartData(BaseModel):
    """Data for AGENT_START event."""

    task: str
    task_id: Optional[str] = None
    depth: int = 0
    parent_task_id: Optional[str] = None


class AgentEndData(BaseModel):
    """Data for AGENT_END event."""

    task: str
    task_id: Optional[str] = None
    confidence_score: float
    notes: Optional[str] = None
    thought_summary: Optional[str] = None
    attempts_count: int = 0
    attempts: list[dict[str, Any]] = Field(default_factory=list)


class AgentErrorData(BaseModel):
    """Data for AGENT_ERROR event."""

    task: str
    task_id: Optional[str] = None
    error_type: str
    error_message: str
    partial_reasoning: Optional[str] = None


class AgentThoughtData(BaseModel):
    """Data for AGENT_THOUGHT event - agent's reasoning during execution."""

    thought: str
    summary: Optional[str] = None
    relevance: float = 0.5


class AgentRoutedData(BaseModel):
    """Data for AGENT_ROUTED event."""

    task: str
    selected_agent: str
    reasoning: str
    available_agents: list[str] = Field(default_factory=list)


class ToolCallStartData(BaseModel):
    """Data for TOOL_CALL_START event."""

    tool_name: str
    tool_call_id: Optional[str] = None
    args: str = ""  # Truncated args string (max 500 chars)


class ToolCallEndData(BaseModel):
    """Data for TOOL_CALL_END event."""

    tool_name: str
    tool_call_id: Optional[str] = None
    success: bool
    result: str = ""  # Truncated result string (max 1000 chars)
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class ApprovalRequiredData(BaseModel):
    """Data for APPROVAL_REQUIRED event - tool waiting for user approval."""

    request_id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    description: str


class ApprovalResponseData(BaseModel):
    """Data for APPROVAL_RESPONSE event - user response to approval request."""

    request_id: str
    approved: bool
    modified_args: Optional[dict[str, Any]] = None


class WorkflowInterruptedData(BaseModel):
    """Data for WORKFLOW_INTERRUPTED event."""

    reason: str


class TaskCreatedData(BaseModel):
    """Data for TASK_CREATED event."""

    task: str
    task_id: str
    depth: int
    parent_task_id: Optional[str] = None
    initial_confidence: float = 0.0


class TaskExpandedData(BaseModel):
    """Data for TASK_EXPANDED event."""

    parent_task: str
    parent_task_id: str
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    subtask_count: int = 0


class TaskStatusChangedData(BaseModel):
    """Data for TASK_STATUS_CHANGED event."""

    task: str
    task_id: str
    old_status: str
    new_status: str
    confidence_score: Optional[float] = None


class ConfidenceUpdateData(BaseModel):
    """Data for CONFIDENCE_UPDATE event."""

    task: str
    task_id: str
    old_confidence: float
    new_confidence: float
    decision: str  # "fail", "expand", "refine", "validate"


class ValidationResultData(BaseModel):
    """Data for VALIDATION_RESULT event."""

    task: str
    task_id: str
    valid: bool
    confidence_score: float
    critique: str
    validation_token: Optional[str] = None


class ExecutionRecordData(BaseModel):
    """Data for EXECUTION_RECORD event."""

    action: str  # "HTTP Request", "Script Execution", etc.
    target_endpoint: Optional[str] = None
    technique: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_status: str  # "success", "failed", "blocked", "partial", "error"
    key_finding: Optional[str] = None
    response_summary: Optional[str] = None


class LogMessageData(BaseModel):
    """Data for LOG_MESSAGE event."""

    message: str
    level: str = "info"  # "debug", "info", "warning", "error"
    source: Optional[str] = None


# Union of all event data types
EventData = Union[
    AgentStartData,
    AgentEndData,
    AgentErrorData,
    AgentThoughtData,
    AgentRoutedData,
    ToolCallStartData,
    ToolCallEndData,
    ApprovalRequiredData,
    ApprovalResponseData,
    WorkflowInterruptedData,
    TaskCreatedData,
    TaskExpandedData,
    TaskStatusChangedData,
    ConfidenceUpdateData,
    ValidationResultData,
    ExecutionRecordData,
    LogMessageData,
    dict[str, Any],  # Fallback for untyped events
]


# =============================================================================
# Main Event Model
# =============================================================================


class AgentEvent(BaseModel):
    """Event emitted during agent execution for streaming to frontend.

    This is the main event model that wraps typed event data with
    common metadata like timestamp, session_id, agent_name, and event type.
    """

    type: EventType
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: str
    agent_name: Optional[str] = None
    task_id: Optional[str] = None
    data: EventData = Field(default_factory=dict)

    # ==========================================================================
    # Factory methods for creating typed events
    # ==========================================================================

    @classmethod
    def agent_start(
        cls,
        session_id: str,
        agent_name: str,
        task: str,
        task_id: Optional[str] = None,
        depth: int = 0,
        parent_task_id: Optional[str] = None,
    ) -> "AgentEvent":
        """Create an AGENT_START event."""
        return cls(
            type=EventType.AGENT_START,
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id,
            data=AgentStartData(
                task=task,
                task_id=task_id,
                depth=depth,
                parent_task_id=parent_task_id,
            ),
        )

    @classmethod
    def agent_end(
        cls,
        session_id: str,
        agent_name: str,
        task: str,
        confidence_score: float,
        task_id: Optional[str] = None,
        notes: Optional[str] = None,
        thought_summary: Optional[str] = None,
        attempts: Optional[list[dict[str, Any]]] = None,
    ) -> "AgentEvent":
        """Create an AGENT_END event."""
        return cls(
            type=EventType.AGENT_END,
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id,
            data=AgentEndData(
                task=task,
                task_id=task_id,
                confidence_score=confidence_score,
                notes=notes,
                thought_summary=thought_summary,
                attempts_count=len(attempts) if attempts else 0,
                attempts=attempts or [],
            ),
        )

    @classmethod
    def agent_error(
        cls,
        session_id: str,
        agent_name: str,
        task: str,
        error_type: str,
        error_message: str,
        task_id: Optional[str] = None,
        partial_reasoning: Optional[str] = None,
    ) -> "AgentEvent":
        """Create an AGENT_ERROR event."""
        return cls(
            type=EventType.AGENT_ERROR,
            session_id=session_id,
            agent_name=agent_name,
            task_id=task_id,
            data=AgentErrorData(
                task=task,
                task_id=task_id,
                error_type=error_type,
                error_message=error_message,
                partial_reasoning=partial_reasoning,
            ),
        )

    @classmethod
    def agent_thought(
        cls,
        session_id: str,
        agent_name: str,
        thought: str,
        summary: Optional[str] = None,
        relevance: float = 0.5,
    ) -> "AgentEvent":
        """Create an AGENT_THOUGHT event."""
        return cls(
            type=EventType.AGENT_THOUGHT,
            session_id=session_id,
            agent_name=agent_name,
            data=AgentThoughtData(
                thought=thought,
                summary=summary,
                relevance=relevance,
            ),
        )

    @classmethod
    def agent_routed(
        cls,
        session_id: str,
        task: str,
        selected_agent: str,
        reasoning: str,
        available_agents: Optional[list[str]] = None,
    ) -> "AgentEvent":
        """Create an AGENT_ROUTED event."""
        return cls(
            type=EventType.AGENT_ROUTED,
            session_id=session_id,
            agent_name=selected_agent,
            data=AgentRoutedData(
                task=task,
                selected_agent=selected_agent,
                reasoning=reasoning,
                available_agents=available_agents or [],
            ),
        )

    @classmethod
    def tool_call_start(
        cls,
        session_id: str,
        agent_name: str,
        tool_name: str,
        args: str = "",
        tool_call_id: Optional[str] = None,
    ) -> "AgentEvent":
        """Create a TOOL_CALL_START event."""
        return cls(
            type=EventType.TOOL_CALL_START,
            session_id=session_id,
            agent_name=agent_name,
            data=ToolCallStartData(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                args=args[:500] if args else "",  # Truncate
            ),
        )

    @classmethod
    def tool_call_end(
        cls,
        session_id: str,
        agent_name: str,
        tool_name: str,
        success: bool,
        result: str = "",
        error: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> "AgentEvent":
        """Create a TOOL_CALL_END event."""
        return cls(
            type=EventType.TOOL_CALL_END,
            session_id=session_id,
            agent_name=agent_name,
            data=ToolCallEndData(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                success=success,
                result=result[:1000] if result else "",  # Truncate
                error=error,
                duration_ms=duration_ms,
            ),
        )

    @classmethod
    def approval_required(
        cls,
        session_id: str,
        agent_name: str,
        request_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        description: str,
    ) -> "AgentEvent":
        """Create an APPROVAL_REQUIRED event."""
        return cls(
            type=EventType.APPROVAL_REQUIRED,
            session_id=session_id,
            agent_name=agent_name,
            data=ApprovalRequiredData(
                request_id=request_id,
                tool_name=tool_name,
                tool_args=tool_args,
                description=description,
            ),
        )

    @classmethod
    def workflow_interrupted(
        cls,
        session_id: str,
        reason: str,
    ) -> "AgentEvent":
        """Create a WORKFLOW_INTERRUPTED event."""
        return cls(
            type=EventType.WORKFLOW_INTERRUPTED,
            session_id=session_id,
            data=WorkflowInterruptedData(reason=reason),
        )

    @classmethod
    def task_expanded(
        cls,
        session_id: str,
        parent_task: str,
        parent_task_id: str,
        subtasks: list[dict[str, Any]],
    ) -> "AgentEvent":
        """Create a TASK_EXPANDED event."""
        return cls(
            type=EventType.TASK_EXPANDED,
            session_id=session_id,
            task_id=parent_task_id,
            data=TaskExpandedData(
                parent_task=parent_task,
                parent_task_id=parent_task_id,
                subtasks=subtasks,
                subtask_count=len(subtasks),
            ),
        )

    @classmethod
    def confidence_update(
        cls,
        session_id: str,
        task: str,
        task_id: str,
        old_confidence: float,
        new_confidence: float,
        decision: str,
    ) -> "AgentEvent":
        """Create a CONFIDENCE_UPDATE event."""
        return cls(
            type=EventType.CONFIDENCE_UPDATE,
            session_id=session_id,
            task_id=task_id,
            data=ConfidenceUpdateData(
                task=task,
                task_id=task_id,
                old_confidence=old_confidence,
                new_confidence=new_confidence,
                decision=decision,
            ),
        )

    @classmethod
    def validation_result(
        cls,
        session_id: str,
        task: str,
        task_id: str,
        valid: bool,
        confidence_score: float,
        critique: str,
        validation_token: Optional[str] = None,
    ) -> "AgentEvent":
        """Create a VALIDATION_RESULT event."""
        return cls(
            type=EventType.VALIDATION_RESULT,
            session_id=session_id,
            task_id=task_id,
            data=ValidationResultData(
                task=task,
                task_id=task_id,
                valid=valid,
                confidence_score=confidence_score,
                critique=critique,
                validation_token=validation_token,
            ),
        )

    @classmethod
    def log_message(
        cls,
        session_id: str,
        message: str,
        level: str = "info",
        source: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> "AgentEvent":
        """Create a LOG_MESSAGE event."""
        return cls(
            type=EventType.LOG_MESSAGE,
            session_id=session_id,
            agent_name=agent_name,
            data=LogMessageData(
                message=message,
                level=level,
                source=source,
            ),
        )


# =============================================================================
# JSON-RPC Error Codes
# =============================================================================


class RPCErrorCode:
    """JSON-RPC 2.0 error codes."""

    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Custom error codes (reserved range: -32000 to -32099)
    COMPONENT_ERROR = -32001
    INITIALIZATION_FAILED = -32002
    HEALTH_CHECK_FAILED = -32003
    SHUTDOWN_ERROR = -32004
    EVENT_STREAM_ERROR = -32005
    APPROVAL_ERROR = -32006
    INTERRUPT_ERROR = -32007


__all__ = [
    # Component models
    "ComponentStatus",
    "ComponentState",
    "InitResult",
    "HealthResult",
    "AllHealthResult",
    # Event types
    "EventType",
    # Event data models
    "AgentStartData",
    "AgentEndData",
    "AgentErrorData",
    "AgentThoughtData",
    "AgentRoutedData",
    "ToolCallStartData",
    "ToolCallEndData",
    "ApprovalRequiredData",
    "ApprovalResponseData",
    "WorkflowInterruptedData",
    "TaskCreatedData",
    "TaskExpandedData",
    "TaskStatusChangedData",
    "ConfidenceUpdateData",
    "ValidationResultData",
    "ExecutionRecordData",
    "LogMessageData",
    "EventData",
    # Main event model
    "AgentEvent",
    # Error codes
    "RPCErrorCode",
]
