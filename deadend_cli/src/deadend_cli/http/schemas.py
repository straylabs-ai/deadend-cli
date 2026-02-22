# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Generic / shared
# -----------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Generic message response."""

    status: str = "ok"
    message: Optional[str] = None


# -----------------------------------------------------------------------------
# Init (reuse rpc_models InitResult, AllInitResult via response_model)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Health (reuse HealthResult, AllHealthResult)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Events / control
# -----------------------------------------------------------------------------


class InterruptRequest(BaseModel):
    """Request to interrupt a session."""

    session_id: str = Field(..., description="Session ID to interrupt")
    reason: str = Field(default="User request interruption", description="Reason for interruption")


class InterruptResponse(BaseModel):
    """Response after interrupting a session."""

    status: str = "interrupted"
    session_id: str


class ApprovalRequest(BaseModel):
    """Request to respond to an approval (approve or reject)."""

    request_id: str = Field(..., description="Approval request ID")
    approved: bool = Field(default=False, description="Whether the action is approved")
    modified_args: Optional[dict[str, Any]] = Field(default=None, description="Optional modified tool arguments")


class ApprovalResponse(BaseModel):
    """Response after responding to an approval."""

    status: str  # "approved" | "rejected"
    request_id: str


class ApprovalModeResponse(BaseModel):
    """Current approval mode status."""

    approval_mode: bool


# -----------------------------------------------------------------------------
# LLM
# -----------------------------------------------------------------------------


class SetProviderRequest(BaseModel):
    """Set current LLM provider."""

    provider: str = Field(..., description="Provider name (e.g. openai, anthropic)")


class AddModelRequest(BaseModel):
    """Add a new model provider."""

    provider: str = Field(..., description="Provider name")
    model_name: str = Field(..., description="Model name")
    api_key: Optional[str] = Field(default=None, description="API key if required")
    base_url: Optional[str] = Field(default=None, description="Base URL for API if custom")
    type_model: Optional[str] = Field(default=None, description="e.g. 'embeddings' for embedding models")
    vec_dim: Optional[int] = Field(default=None, description="Vector dimension for embedding models")


class AddModelResponse(BaseModel):
    """Response after adding a model."""

    status: str = "ok"
    provider: str
    model_name: str
    type_model: Optional[str] = None


class LlmProviderResponse(BaseModel):
    """Current LLM provider and model."""

    provider: str
    model: Optional[str] = None


# -----------------------------------------------------------------------------
# Agents
# -----------------------------------------------------------------------------


class InstantiateAgentRequest(BaseModel):
    """Request to create and prepare an agent."""

    target: str = Field(..., description="Target (e.g. URL or identifier)")
    provider: Optional[str] = Field(default=None, description="LLM provider; uses default if omitted")
    model_name: Optional[str] = Field(default=None, description="Model name; uses default if omitted")


class InstantiateAgentResponse(BaseModel):
    """Response with agent ID after instantiation."""

    status: str  # "ok" | "failed"
    agent_id: Optional[str] = Field(default=None, description="UUID of the created agent")
    reason: Optional[str] = Field(default=None, description="Error reason when status is 'failed'")


class EmbedTargetRequest(BaseModel):
    """Request to embed a target for an agent."""

    target: Optional[str] = Field(default=None, description="Target; can reuse agent's target if same")
    agent_id: str = Field(..., description="Agent ID from instantiate_agent")


class RunAgentRequest(BaseModel):
    """Request to run an agent (recursive or supervisor)."""

    agent_id: str = Field(..., description="Agent ID")
    prompt: str = Field(..., description="Task or prompt for the agent")


# Streaming responses use Server-Sent Events; phase + data are in the event payload.
