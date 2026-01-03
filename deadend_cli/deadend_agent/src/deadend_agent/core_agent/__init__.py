# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core agent system using LiteLLM and Instructor.

This module provides a clean, simple agent implementation to replace Pydantic AI.
Philosophy: Simplest implementation that works.

Key components:
- CoreAgent: Main agent class with LiteLLM and Instructor
- SessionMetrics: Per-session usage and metrics tracking
- Telemetry: Multi-backend OpenTelemetry support
"""

from __future__ import annotations


class UsageLimitExceeded(Exception):
    """Raised when agent usage limits are exceeded."""
    pass


# Import main classes
from .core_agent import CoreAgent, AgentResult, TokenUsageInfo
from .session_metrics import SessionMetrics, get_session_metrics, TokenUsage

__all__ = [
    "CoreAgent",
    "AgentResult",
    "TokenUsageInfo",
    "SessionMetrics",
    "TokenUsage",
    "get_session_metrics",
    "UsageLimitExceeded",
]
