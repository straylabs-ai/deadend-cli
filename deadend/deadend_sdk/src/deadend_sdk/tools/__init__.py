# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Security research tools for AI agent interactions and automation.

This module provides a collection of tools that AI agents can use for
security research, including shell execution, HTTP requests, code analysis,
and knowledge base queries for comprehensive security assessments.
"""

from .shell import sandboxed_shell_tool
from .browser_automation import (
    is_valid_request_detailed,
    pw_send_payload,
    cleanup_playwright_sessions,
    cleanup_playwright_session_for_target
)
from .playwright_requester import (
    send_payload_with_playwright,
)
from .webapp_code_rag import webapp_code_rag


__all__ = [
    "sandboxed_shell_tool", 
    "is_valid_request_detailed", 
    "webapp_code_rag",
    "send_payload_with_playwright",
    "pw_send_payload",
    "cleanup_playwright_sessions",
    "cleanup_playwright_session_for_target"
]