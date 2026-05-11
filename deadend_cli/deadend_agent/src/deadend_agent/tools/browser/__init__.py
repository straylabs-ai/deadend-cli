# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Browser automation: LLM-facing tool plus Pydoll helpers.

The **browser_run_steps** tool lives in ``run_browser_steps_tool.py``. It forwards to
``run_browser_steps`` which orchestrates a :class:`BrowserSession`.

:class:`BrowserSession` (in ``browser.py``) is the generic engine: lifecycle,
navigation, DOM interaction, state extraction, and session import/export.
"""

from deadend_agent.tools.browser.browser import (
    BrowserSession,
    CheckStep,
    ClickStep,
    FillStep,
    InteractionStep,
    PressStep,
    SelectStep,
)
from deadend_agent.tools.browser.run_browser_steps_tool import (
    BrowserCheckStep,
    BrowserClickStep,
    BrowserFillStep,
    BrowserPressStep,
    BrowserSelectStep,
    BrowserStep,
    browser_run_steps,
    parse_browser_steps,
    browser_step_to_interaction,
)
from deadend_agent.tools.browser.authenticate import authenticate, authenticate_service
from deadend_agent.tools.browser.validate_refresh import (
    refresh_auth_context,
    refresh_auth_context_service,
    validate_auth_context,
    validate_auth_context_service,
)

__all__ = [
    "BrowserSession",
    "BrowserStep",
    "BrowserFillStep",
    "BrowserSelectStep",
    "BrowserCheckStep",
    "BrowserClickStep",
    "BrowserPressStep",
    "parse_browser_steps",
    "run_browser_steps",
    "browser_run_steps",
    "authenticate",
    "authenticate_service",
    "validate_auth_context",
    "validate_auth_context_service",
    "refresh_auth_context",
    "refresh_auth_context_service",
    "CheckStep",
    "ClickStep",
    "FillStep",
    "InteractionStep",
    "PressStep",
    "SelectStep",
    "browser_step_to_interaction",
]
