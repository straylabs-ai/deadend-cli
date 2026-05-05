from __future__ import annotations
from pydoll.exceptions import ArgumentAlreadyExistsInOptions
from playwright.async_api import expect

import json
import math
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Literal


from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.browser.tab import Tab
from pydoll.constants import Key
from pydoll.elements.web_element import WebElement


def _timeout_seconds(timeout_ms: float | None, *, default_ms: float = 30_000, cap_s: int = 600) -> int:
    ms = float(timeout_ms if timeout_ms is not None else default_ms)
    seconds = max(1, int(math.ceil(ms / 1000.0)))
    return min(seconds, cap_s)

def _resolve_keyboard_key(key_name: str) -> Key:
    name = key_name.strip()
    aliases = {
        "Return": "ENTER",
        "Esc": "ESCAPE",
        "Spacebar": "SPACE",
        " ": "SPACE",
    }
    enum_name = aliases.get(name, name.replace(" ", "_").upper())
    if hasattr(Key, enum_name):
        return getattr(Key, enum_name)
    if len(name) == 1 and name.isalpha():
        letter = name.upper()
        if hasattr(Key, letter):
            return getattr(Key, letter)
    raise ValueError(
        f"Unsupported key_name {key_name!r} for Pydoll; use names from pydoll.constants.Key "
        f"(e.g. Enter → ENTER)."
    )


async def _query_one(tab: Tab, selector: str, *, timeout_ms: float | None) -> WebElement:
    timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
    el = await tab.query(selector, timeout=timeout_s, find_all=False, raise_exc=True)
    if el is None:
        raise RuntimeError(f"Element not found for selector: {selector!r}")
    if isinstance(el, list):
        raise RuntimeError(f"Expected one element for selector: {selector!r}")
    return el


async def _select_with_script(
    tab: Tab,
    selector: str,
    raw_value: Any,
    by: Literal["value", "label", "index"],
    *,
    timeout_ms: float | None,
) -> None:
    await _query_one(tab, selector, timeout_ms=timeout_ms)
    sel_json = json.dumps(selector)
    if by == "index":
        idx = int(raw_value)
        script = f"""
        (() => {{
          const el = document.querySelector({sel_json});
          if (!el || el.tagName !== 'SELECT') throw new Error('Expected SELECT');
          const idx = {idx};
          if (idx < 0 || idx >= el.options.length) throw new Error('index out of range');
          el.selectedIndex = idx;
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }})()
        """
    else:
        val_json = json.dumps(str(raw_value))
        by_json = json.dumps(by)
        script = f"""
        (() => {{
          const el = document.querySelector({sel_json});
          if (!el || el.tagName !== 'SELECT') throw new Error('Expected SELECT');
          const by = {by_json};
          const val = {val_json};
          let idx = -1;
          if (by === 'value') {{
            for (let i = 0; i < el.options.length; i++) {{
              if (String(el.options[i].value) === val) {{ idx = i; break; }}
            }}
          }} else {{
            for (let i = 0; i < el.options.length; i++) {{
              if (String(el.options[i].textContent).trim() === val) {{ idx = i; break; }}
            }}
          }}
          if (idx < 0 || idx >= el.options.length) throw new Error('option not found');
          el.selectedIndex = idx;
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }})()
        """
    await tab.execute_script(script)


async def _set_checked_with_script(
    tab: Tab,
    selector: str,
    checked: bool,
    *,
    timeout_ms: float | None,
) -> None:
    await _query_one(tab, selector, timeout_ms=timeout_ms)
    lit = "true" if checked else "false"
    script = f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) throw new Error('element not found');
      el.checked = {lit};
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """
    await tab.execute_script(script)


class BrowserSession:
    """
    BrowserSession object uses **Pydoll** (Chrome DevTools Protocol) to instanciate
    a new tab to work on, with the right specs and methods to retrieve and use the 
    right cookies, headers, storage... Basically giving a tab that could be used
    for navigation steps.
    """

    def __init__(
        self,
        headless: bool = True,
        verify_ssl: bool = True,
        proxy_url: str | None = None,
        user_agent: str | None = None,
    ) -> None:

        self._browser: Chrome | None = None
        # Browser
        self._tab: Tab | None = None
        # tab
        self._default_tab: Tab | None = None
        # default tab
        self._headless = headless
        # whether to run in headless
        self._verify_ssl = verify_ssl
        # whether to verify SSL
        self._proxy_url = proxy_url
        # if we link to a proxy via burp, zap, other proxies...
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        # User-agent
        self._chrome_options: ChromiumOptions | None = None
        # Chrome options instanciated with the browser
        self._browser_contexts: list[str] = []
        # Browser contexts created and available in the browser

    def _build_chromium_options(self):
        """
        Instanciation chromium options correctly.
        Adding all the arguments for stealth, proxy, headless and user-agent.
        """
        self._chrome_options = ChromiumOptions()
        self._chrome_options.headless = self._headless
        try:
            self._chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            self._chrome_options.add_argument('--window-size=1920,1080')
            self._chrome_options.add_argument('--disable-extensions')
            self._chrome_options.add_argument('--disable-gpu')
            self._chrome_options.add_argument('--disable-dev-shm-usage')
            self._chrome_options.add_argument('--disable-sync')
            self._chrome_options.add_argument('--disable-translate')
            if self._proxy_url:
                self._chrome_options.add_argument(f"--proxy-server={self._proxy_url}")
            if not self._verify_ssl:
                self._chrome_options.add_argument("ignore-certification-errors")
            if self._user_agent:
                self._chrome_options.add_argument(f"--user-agent={self._user_agent}")
            else:
                self._chrome_options.add_argument(
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
        except ArgumentAlreadyExistsInOptions as e:
            print(f"Argument already exists in chromium options : {e}")

    @property
    def started(self) -> bool:
        return self._chrome is not None and self._tab is not None

    @property
    def browser(self) -> Chrome | None:
        """Active Pydoll ``Chrome`` instance, if started."""
        return self._browser

    @property
    def tab(self) -> Tab | None:
        """Primary tab used for ``goto`` / steps, if started."""
        return self._tab

    async def start(self) -> None:
        if self.started:
            return

        options = self._build_chromium_options()
        self._browser = Chrome(options=options)
        await self._browser.__aenter__()

        self._tab = await self._browser.start()
        self._browser_contexts.append(await self._browser.create_browser_context())

        self._default_tab = self._tab

    async def stop(self) -> None:
        if self._chrome is not None:
            await self._chrome.__aexit__(None, None, None)
        self._chrome = None
        self._tab = None
        self._default_tab = None

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        await self.stop()
        return None

    async def new_tab(self) -> Tab:
        if not self._browser:
            raise RuntimeError("BrowserSession is not started; call start() or use async with.")
        return await self._browser.new_tab()

    async def default_page(self) -> Tab:
        """Return the main tab (Pydoll ``Tab``). Named ``default_page`` for backward compatibility."""
        if self._default_tab is None:
            raise RuntimeError("BrowserSession is not started; call start() or use async with.")
        return self._default_tab

    async def goto(
        self,
        url: str,
        *,
        page: Tab | None = None,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "load",
        timeout_ms: float | None = None,
    ) -> None:
        del wait_until  # Pydoll waits for configured page load state; kept for API compatibility.
        tab = page or await self.default_page()
        timeout_s = _timeout_seconds(timeout_ms, default_ms=30_000)
        await tab.go_to(url, timeout=timeout_s)

    @staticmethod
    def _context_value(
        context: Mapping[str, Any],
        key: str,
        *,
        optional: bool,
    ) -> Any:
        if key not in context:
            if optional:
                return None
            raise KeyError(key)
        return context[key]

    @staticmethod
    async def fill_from_context(
        tab: Tab,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        optional: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        value = BrowserSession._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        text = "" if value is None else str(value)
        el = await _query_one(tab, selector, timeout_ms=timeout_ms)
        await el.clear()
        await el.insert_text(text)

    @staticmethod
    async def select_from_context(
        tab: Tab,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        by: Literal["value", "label", "index"] = "value",
        optional: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        value = BrowserSession._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        await _select_with_script(tab, selector, value, by, timeout_ms=timeout_ms)

    @staticmethod
    async def check_from_context(
        tab: Tab,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        optional: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        value = BrowserSession._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        await _set_checked_with_script(tab, selector, bool(value), timeout_ms=timeout_ms)

    @staticmethod
    async def click(
        tab: Tab,
        selector: str,
        *,
        timeout_ms: float | None = None,
        **kwargs: Any,
    ) -> None:
        del kwargs
        el = await _query_one(tab, selector, timeout_ms=timeout_ms)
        await el.click()

    @staticmethod
    async def press(
        tab: Tab,
        selector: str,
        key: str = "Enter",
        *,
        timeout_ms: float | None = None,
        **kwargs: Any,
    ) -> None:
        del kwargs
        el = await _query_one(tab, selector, timeout_ms=timeout_ms)
        await el.focus()
        await tab.keyboard.press(_resolve_keyboard_key(key))

    @staticmethod
    async def run_steps(
        tab: Tab,
        steps: Sequence[InteractionStep],
        context: Mapping[str, Any],
        *,
        optional_keys: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        for step in steps:
            if isinstance(step, FillStep):
                await BrowserSession.fill_from_context(
                    tab,
                    step.selector,
                    step.context_key,
                    context,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                )
            elif isinstance(step, SelectStep):
                await BrowserSession.select_from_context(
                    tab,
                    step.selector,
                    step.context_key,
                    context,
                    by=step.by,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                )
            elif isinstance(step, CheckStep):
                await BrowserSession.check_from_context(
                    tab,
                    step.selector,
                    step.context_key,
                    context,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                )
            elif isinstance(step, ClickStep):
                await BrowserSession.click(tab, step.selector, timeout_ms=timeout_ms)
            elif isinstance(step, PressStep):
                await BrowserSession.press(tab, step.selector, step.key, timeout_ms=timeout_ms)
            else:
                raise TypeError(f"Unsupported step type: {type(step)!r}")


async def run_browser_steps(
    *,
    page_url: str,
    context: Mapping[str, Any],
    steps: Sequence[BrowserStep | dict[str, Any]],
    headless: bool = True,
    verify_ssl: bool = True,
    proxy_url: str | None = None,
    optional_missing_context_keys: bool = False,
    navigation_timeout_ms: float | None = 30_000,
    action_timeout_ms: float | None = 15_000,
) -> dict[str, Any]:
    """Run a full headless browser interaction from arguments the model can supply as JSON.

    **What the model passes (conceptually the tool arguments):**

    - ``page_url`` (str): Full URL, including scheme (e.g. ``https://host/login``). This page is
      loaded once before any step; redirects are followed by the browser.
    - ``context`` (object): Flat string-keyed map. Only ``fill``, ``select``, and ``check`` steps
      read from it via each step's ``key`` field (e.g. ``key`` ``"password"`` → ``context["password"]``).
      Values should be strings, booleans, or numbers; they are coerced as needed. The model does
      not pass a Pydoll ``Tab`` handle.
    - ``steps`` (array): Ordered list of step objects. Each object **must** include ``action``.
      Allowed shapes are exactly those documented on ``BrowserFillStep``, ``BrowserSelectStep``,
      ``BrowserCheckStep``, ``BrowserClickStep``, and ``BrowserPressStep``. Extra properties are
      forbidden on each step object.

    **How it works (runtime order):**

    1. Start Chromium via **Pydoll** (CDP) and a fresh profile (optional ``proxy_url``; if
       ``verify_ssl`` is false, certificate errors are ignored using Chrome flags).
    2. Open ``page_url`` on the initial tab with ``navigation_timeout_ms`` (converted to seconds
       for ``tab.go_to``).
    3. Execute ``steps`` **in order** on that tab. Each step uses ``action_timeout_ms`` when
       resolving selectors. Any uncaught error stops the run and is recorded in the return value.
    4. Stop the browser and close the CDP session.

    **Flags:** ``optional_missing_context_keys`` — if true, a step whose ``key`` is missing from
    ``context`` is skipped for fill/select/check; if false, that situation raises and is reported
    as an error string.

    **Engine parameters (usually set by code, not spelled out by the model):** ``headless`` runs
    Chromium without a visible window. ``verify_ssl`` / ``proxy_url`` tune TLS and proxy similarly
    to other browser tooling in this project. ``navigation_timeout_ms`` caps the initial navigation;
    ``action_timeout_ms`` caps each selector wait inside a step.

    **Return value (always a dict, suitable to echo back to the model):**

    - ``success`` (bool): True only if navigation and every step completed without exception.
    - ``error`` (str | None): Human-readable error message on failure; ``None`` on success.
    - ``final_url`` (str | None): Document URL after the last step (may differ from ``page_url``).
    - ``page_title`` (str | None): Document title after the last step.
    - ``steps_run`` (int): Count of validated steps (length of ``steps``), even if a step failed
      partway through (then ``success`` is false and ``error`` is set).

    The model never passes a Pydoll ``Tab``; only JSON-serializable fields above.
    """
    parsed = parse_browser_steps(steps)
    internal = [browser_step_to_interaction(s) for s in parsed]
    out: dict[str, Any] = {
        "success": False,
        "error": None,
        "final_url": None,
        "page_title": None,
        "steps_run": len(parsed),
    }
    try:
        async with BrowserSession(
            headless=headless,
            verify_ssl=verify_ssl,
            proxy_url=proxy_url,
        ) as browser:
            await browser.goto(page_url, timeout_ms=navigation_timeout_ms)
            tab = await browser.default_page()
            await BrowserSession.run_steps(
                tab,
                internal,
                context,
                optional_keys=optional_missing_context_keys,
                timeout_ms=action_timeout_ms,
            )
            out["final_url"] = await tab.current_url
            out["page_title"] = await tab.title
            out["success"] = True
    except Exception as e:
        out["error"] = str(e)
    return out
