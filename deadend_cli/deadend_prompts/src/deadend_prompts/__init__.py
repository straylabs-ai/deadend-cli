# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Prompt template system for AI agent instructions and tool descriptions.

This module provides template rendering functionality for generating
dynamic prompts, agent instructions, and tool descriptions using Jinja2
templates for the security research framework.
"""

from .template_renderer import TemplateToolRenderer, TemplateAgentRenderer,\
     render_tool_description, render_agent_instructions

__all__ = [
    "render_agent_instructions",
    "render_tool_description",
    "TemplateAgentRenderer",
    "TemplateToolRenderer"
]