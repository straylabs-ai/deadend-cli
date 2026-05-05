# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Browser automation: LLM-facing tool plus Playwright helpers.

The **browser_run_steps** tool lives in ``run_browser_steps_tool.py``. It forwards to
``run_browser_steps`` in ``browser.py`` with ``proxy_url`` from ``RequesterDeps`` and a fixed
headless browser. See the docstrings on ``browser_run_steps`` and ``run_browser_steps`` for the
exact JSON the model must pass and the dict returned to the model.
"""

from deadend_agent.tools.browser.browser import (
    BrowserCheckStep,
    BrowserClickStep,
    BrowserFillStep,
    BrowserPressStep,
    BrowserSelectStep,
    BrowserStep,
    BrowserTool,
    CheckStep,
    ClickStep,
    FillStep,
    InteractionStep,
    PressStep,
    SelectStep,
    parse_browser_steps,
    run_browser_steps,
)
from deadend_agent.tools.browser.run_browser_steps_tool import browser_run_steps

__all__ = [
    "BrowserTool",
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
]
