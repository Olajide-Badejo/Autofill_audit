"""The one fixture in this repository with a shelf life, and its alarm.

``tests/fixtures/checkout_hostile.html`` holds a run of consecutive expiry years.
Group detection recognises such a run only when it starts inside a window
relative to the current year (spec section 9.5), because that window is what
separates an expiry list from a list of birth years. A static fixture cannot move
with the clock, so one day the window leaves it behind and the split-expiry pair
stops being detected.

That is not a flake. It is a deterministic expiry with a known date, and the
honest thing to do is to say so loudly at the moment it starts to matter rather
than to have the golden snapshots quietly change meaning. The test below fails
with the edit that fixes it.

This is deliberately the **only** clock-dependent assertion in the suite. Every
other test that touches the expiry window freezes the year, per spec section 15's
flake policy.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from autofill_audit.extract.groups import YEAR_WINDOW_BACK, YEAR_WINDOW_FORWARD

FIXTURE = Path("tests") / "fixtures" / "checkout_hostile.html"
_YEAR_OPTION = re.compile(r'<option value="(20\d\d)">')


def test_the_hostile_fixture_expiry_years_are_still_inside_the_window(
    repo_root: Path,
) -> None:
    """When this fails, edit the year list and regenerate the snapshots."""
    document = (repo_root / FIXTURE).read_text(encoding="utf-8")
    years = [int(match) for match in _YEAR_OPTION.findall(document)]
    assert years, "the fixture no longer holds a year list at all"
    first = years[0]
    now = dt.date.today().year
    assert now - YEAR_WINDOW_BACK <= first <= now + YEAR_WINDOW_FORWARD, (
        f"{FIXTURE} starts its expiry list at {first}, which is outside the "
        f"detection window for the year {now}. Group detection will no longer see "
        "a split expiry pair on this page, so the fixture no longer tests what it "
        "says it tests. Edit the option list to start at the current year, then "
        "run python scripts/refresh_golden.py and read the diff."
    )


def test_the_year_list_is_consecutive_and_long_enough_to_be_detected(
    repo_root: Path,
) -> None:
    """The other half of the detection rule, which an edit could break."""
    document = (repo_root / FIXTURE).read_text(encoding="utf-8")
    years = [int(match) for match in _YEAR_OPTION.findall(document)]
    assert years == list(range(years[0], years[0] + len(years)))
