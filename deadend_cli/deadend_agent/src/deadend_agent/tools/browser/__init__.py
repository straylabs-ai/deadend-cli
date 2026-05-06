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
    run_browser_steps,
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
    "CheckStep",
    "ClickStep",
    "FillStep",
    "InteractionStep",
    "PressStep",
    "SelectStep",
    "browser_step_to_interaction",
]
