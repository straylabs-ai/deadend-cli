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

from .python_interpreter import run_python_file, read_auth_storage
from .webapp_code_rag import webapp_code_rag
from .grep import grep_session_logs
from .tool_wrappers import with_tool_events, wrap_tool_with_events


__all__ = [
    # Shell
    "sandboxed_shell_tool",
    #Python interpreter
    "run_python_file",
    "read_auth_storage",
    # Webapp Rag
    "webapp_code_rag",
    # Playwright
    "is_valid_request_detailed",
    "pw_send_payload",
    "cleanup_playwright_sessions",
    "cleanup_playwright_session_for_target",
    # Grep
    "grep_session_logs",
    # Tool wrappers
    "with_tool_events",
    "wrap_tool_with_events",
]