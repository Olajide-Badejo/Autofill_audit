"""Playwright launch, navigation, and teardown with bounded waits.

Uses the **synchronous** Playwright API, for the reasons in spec section 5.5:
the CLI does one thing at a time, so async buys nothing and costs the ability to
call the extractor from an ordinary function, from a pytest test, and from a
notebook without event-loop ceremony.

Never follows links, never submits, never types (spec sections 0.4 and 5.1).
The only navigation is the one the user asked for, and ``--file`` reaches a
local file through ``file://`` rather than through a server.

The waiting policy (spec section 9.6)
-------------------------------------

Three bounded stages, in order, and no unbounded wait anywhere:

1. the ``load`` state, bounded by ``load_timeout_ms``;
2. network idle **or** ``network_idle_ms``, whichever comes first, because a
   page with a long-poll connection never goes idle and waiting for one that
   never arrives is how a CLI hangs;
3. a DOM-quiet period: ``quiet_ms`` with no mutation, bounded in total by
   ``settle_budget_ms``.

Stage 3 is observed rather than slept through. A ``MutationObserver`` installed
before any page script runs records when the last mutation happened and how many
form controls have been added since load, so the settle can report that it saw
something appear rather than merely that it waited. That distinction is what
spec section 15's flake policy asks for: the injected-field fixture asserts on
the mechanism, never on a duration.

If the budget expires while mutations are still arriving, extraction proceeds on
what exists and the result carries an ``INCOMPLETE`` warning. Never wait
unbounded, and never report a short list as if it were the whole page.

Errors are typed and the CLI maps them to exit codes at P3 (spec section 11.5).
Nothing here prints, and nothing here calls ``sys.exit``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from autofill_audit.descriptors import SettleReport

__all__ = [
    "DOM_QUIET_MS",
    "LOAD_TIMEOUT_MS",
    "NETWORK_IDLE_TIMEOUT_MS",
    "SETTLE_BUDGET_MS",
    "SUPPORTED_SCHEMES",
    "LoadBudget",
    "LoadedPage",
    "LoaderError",
    "NavigationFailedError",
    "NavigationTimeoutError",
    "NotHtmlError",
    "TargetNotFoundError",
    "UnsupportedSchemeError",
    "browser_session",
    "load_page",
    "looks_like_html",
    "settle",
    "target_url",
]

LOAD_TIMEOUT_MS: Final[int] = 15_000
"""How long the ``load`` event may take. Generous, because a slow page is a
real page; bounded, because a page that never loads must not hang a CLI."""

NETWORK_IDLE_TIMEOUT_MS: Final[int] = 5_000
"""How long to wait for network idle before giving up on it and moving on.
Giving up is not a failure: plenty of healthy pages hold a socket open
forever, and the DOM-quiet stage is the one that actually decides."""

DOM_QUIET_MS: Final[int] = 250
"""How long the DOM must go unmutated before the page counts as settled.
Comfortably longer than one animation frame and comfortably shorter than the
gap a page leaves before injecting a field it means a user to see."""

SETTLE_BUDGET_MS: Final[int] = 3_000
"""The total budget for the quiet stage. An animation that mutates the DOM
forever would otherwise hold the quiet period off indefinitely."""

SUPPORTED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "file"})

_HTML_MARKER: Final[re.Pattern[bytes]] = re.compile(
    rb"<\s*(!doctype\s+html|html|head|body|form|div|table|input|select|textarea|p|span|main)\b",
    re.IGNORECASE,
)
_SNIFF_BYTES: Final[int] = 4096

_OBSERVER_SCRIPT: Final[str] = """
(() => {
  if (window.__autofillAuditSettle) { return; }
  const state = { mutations: 0, controlsAdded: 0, lastAt: Date.now() };
  window.__autofillAuditSettle = state;
  const isControl = (node) => {
    if (!node || node.nodeType !== 1) { return false; }
    const tag = node.tagName.toLowerCase();
    return tag === 'input' || tag === 'select' || tag === 'textarea';
  };
  const observer = new MutationObserver((records) => {
    state.mutations += records.length;
    state.lastAt = Date.now();
    for (const record of records) {
      for (const added of record.addedNodes) {
        if (isControl(added)) {
          state.controlsAdded += 1;
        } else if (added.nodeType === 1 && added.querySelectorAll) {
          state.controlsAdded += added.querySelectorAll('input, select, textarea').length;
        }
      }
    }
  });
  const start = () => observer.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true
  });
  if (document.documentElement) {
    start();
  } else {
    document.addEventListener('readystatechange', start, { once: true });
  }
})();
"""

_READ_SETTLE: Final[str] = """
() => {
  const state = window.__autofillAuditSettle;
  if (!state) { return { mutations: 0, controlsAdded: 0, sinceLast: 0 }; }
  return {
    mutations: state.mutations,
    controlsAdded: state.controlsAdded,
    sinceLast: Date.now() - state.lastAt
  };
}
"""


class LoaderError(Exception):
    """Base class for every failure the loader can report.

    Typed so that the CLI can map each one to an exit code without parsing a
    message (spec section 11.5), and so that a caller which only cares that
    loading failed can catch one class.
    """


class UnsupportedSchemeError(LoaderError):
    """The target names a scheme this tool will not open."""


class TargetNotFoundError(LoaderError):
    """A ``--file`` target does not exist, or is not a file."""


class NotHtmlError(LoaderError):
    """A ``--file`` target exists but is not HTML."""


class NavigationTimeoutError(LoaderError):
    """The page did not reach the load state inside the budget."""


class NavigationFailedError(LoaderError):
    """Navigation completed with a status or a failure the audit cannot use."""


@dataclass(frozen=True, slots=True)
class LoadBudget:
    """The four bounds of the waiting policy, in milliseconds.

    A dataclass rather than four arguments so that a test can shrink the whole
    policy in one place, and so that the values a run used can be recorded
    alongside its results (spec section 18).
    """

    load_timeout_ms: int = LOAD_TIMEOUT_MS
    network_idle_ms: int = NETWORK_IDLE_TIMEOUT_MS
    quiet_ms: int = DOM_QUIET_MS
    settle_budget_ms: int = SETTLE_BUDGET_MS


@dataclass(frozen=True, slots=True)
class LoadedPage:
    """A loaded page and what the wait for it observed."""

    page: Page
    settle: SettleReport
    url: str


def looks_like_html(path: Path) -> bool:
    """Whether a local file is plausibly HTML.

    Sniffs the first few kilobytes for a tag rather than trusting the suffix,
    because a saved DOM is routinely called ``.txt`` and a ``.html`` file is
    routinely a PNG somebody renamed. Spec section 15 requires that a file which
    is not HTML produces a diagnostic rather than a traceback, and this is where
    that diagnosis is made.
    """
    try:
        head = path.open("rb").read(_SNIFF_BYTES)
    except OSError:
        return False
    return _HTML_MARKER.search(head) is not None


def target_url(target: str, *, as_file: bool) -> str:
    """Turn a CLI target into a URL, or raise.

    Args:
        target: a URL, or a filesystem path when ``as_file`` is set.
        as_file: whether the target is a local file, which is what ``--file``
            means.

    Raises:
        TargetNotFoundError: the file does not exist or is a directory.
        NotHtmlError: the file exists and is not HTML.
        UnsupportedSchemeError: the URL names a scheme outside
            ``SUPPORTED_SCHEMES``.
    """
    if as_file:
        path = Path(target).expanduser()
        if not path.is_file():
            raise TargetNotFoundError(f"{target}: no such file")
        if not looks_like_html(path):
            raise NotHtmlError(f"{target}: does not look like HTML")
        return path.resolve().as_uri()

    parsed = urlparse(target)
    if parsed.scheme == "":
        raise UnsupportedSchemeError(
            f"{target}: no scheme. Pass --file to audit a local file, "
            f"or write the scheme out in full."
        )
    if parsed.scheme not in SUPPORTED_SCHEMES:
        supported = ", ".join(sorted(SUPPORTED_SCHEMES))
        raise UnsupportedSchemeError(
            f"{target}: scheme {parsed.scheme!r} is not one of {supported}"
        )
    return target


def settle(page: Page, budget: LoadBudget) -> SettleReport:
    """Run the bounded wait of spec section 9.6 and report what it saw.

    Returns as soon as the DOM has been quiet for ``quiet_ms``, or when
    ``settle_budget_ms`` runs out, whichever is first. ``reached_quiet`` says
    which of the two happened, and it is the only thing a caller should branch
    on: the elapsed time is reported for a log, never for a decision.
    """
    network_idle = True
    if budget.network_idle_ms > 0:
        try:
            page.wait_for_load_state("networkidle", timeout=budget.network_idle_ms)
        except PlaywrightTimeout:
            network_idle = False

    started = time.monotonic()
    deadline = started + budget.settle_budget_ms / 1000
    reached_quiet = True
    state: dict[str, float] = {"mutations": 0.0, "controlsAdded": 0.0, "sinceLast": 0.0}
    while True:
        state = _read_settle_state(page)
        if state["sinceLast"] >= budget.quiet_ms:
            break
        if time.monotonic() >= deadline:
            reached_quiet = False
            break
        page.wait_for_timeout(min(budget.quiet_ms, 50))

    return SettleReport(
        reached_quiet=reached_quiet,
        waited_ms=(time.monotonic() - started) * 1000,
        mutations_after_load=int(state["mutations"]),
        controls_added_after_load=int(state["controlsAdded"]),
        network_idle=network_idle,
    )


def _read_settle_state(page: Page) -> dict[str, float]:
    """Read the mutation observer's counters out of the page."""
    try:
        raw = page.evaluate(_READ_SETTLE)
    except PlaywrightError:
        return {"mutations": 0.0, "controlsAdded": 0.0, "sinceLast": float("inf")}
    if not isinstance(raw, dict):
        return {"mutations": 0.0, "controlsAdded": 0.0, "sinceLast": float("inf")}
    return {
        "mutations": float(raw.get("mutations", 0)),
        "controlsAdded": float(raw.get("controlsAdded", 0)),
        "sinceLast": float(raw.get("sinceLast", 0)),
    }


@contextmanager
def load_page(
    target: str,
    *,
    as_file: bool = False,
    budget: LoadBudget | None = None,
    headless: bool = True,
    browser: Browser | None = None,
) -> Iterator[LoadedPage]:
    """Open one page, wait for it under the policy, and tear everything down.

    A context manager because a browser that outlives its use is a browser that
    leaks; the page, its context, and the browser are closed on the way out
    whether or not the body raised.

    Args:
        target: a URL, or a path when ``as_file`` is set.
        as_file: audit a local file through ``file://``.
        budget: the waiting policy; the default is the documented one.
        headless: run the browser headless. False exists for a human debugging
            a page by hand, never for CI.
        browser: an already-launched browser to borrow. A test suite that opens
            twenty fixtures pays for one launch instead of twenty; when it is
            passed, it is not closed here.

    Raises:
        NavigationTimeoutError: the load state was not reached in time.
        NavigationFailedError: navigation failed, or answered with a status the
            audit cannot use.
    """
    policy = budget if budget is not None else LoadBudget()
    url = target_url(target, as_file=as_file)

    with ExitStack() as stack:
        if browser is None:
            playwright = stack.enter_context(sync_playwright())
            opened = playwright.chromium.launch(headless=headless)
            stack.callback(opened.close)
        else:
            opened = browser
        context = opened.new_context()
        stack.callback(context.close)
        context.add_init_script(_OBSERVER_SCRIPT)
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="load", timeout=policy.load_timeout_ms)
        except PlaywrightTimeout as error:
            raise NavigationTimeoutError(
                f"{url}: did not reach the load state within {policy.load_timeout_ms} ms"
            ) from error
        except PlaywrightError as error:
            raise NavigationFailedError(f"{url}: navigation failed ({error.message})") from error

        if response is not None and response.status >= 400:
            raise NavigationFailedError(f"{url}: answered with HTTP {response.status}")

        report = settle(page, policy)
        yield LoadedPage(page=page, settle=report, url=page.url)


@contextmanager
def browser_session(*, headless: bool = True) -> Iterator[Browser]:
    """Launch one browser and keep it open for several loads.

    A sweep over hundreds of corpus forms should pay for one browser launch, not
    hundreds. Pass the yielded browser to ``load_page``; each load still gets a
    fresh context, so no page can see another page's storage or cookies.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            browser.close()
