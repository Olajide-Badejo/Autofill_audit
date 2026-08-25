"""Structural group detection (spec section 9.5).

Group detection lives in the extractor rather than in a classifier because it is
a fact about the document, not an inference about meaning. A group the extractor
misses becomes two independent confusing predictions; a group it invents becomes
one wrong finding. Both are testable against fixtures, and both are tested.

Three groups, three mechanisms
------------------------------

**Split expiry.** Two adjacent controls in the same fieldset or the same parent,
one of which offers twelve months and the other a run of consecutive years.
Detection keys on the *option values* first and the *displayed digits* second,
because the corpus renders month names in German and ``1月`` through ``12月`` in
Japanese while every locale keeps the values ``01`` through ``12``. A detector
that read only the display text would fail on two locales out of six.

**The year window is relative and the clock is injectable.** Spec section 9.5
warns against a hardcoded window for a reason: a fixture that hardcodes one
expires, silently, on a January morning, and the test that was protecting the
detector becomes the test that breaks the build. ``now_year`` is a parameter
with no default at the seam that matters, so a test can freeze it.

**Address line runs.** Two or three consecutive text inputs that each look like
one line of one address. "Look like" is a vocabulary match over the normalised
label and identifier tokens plus an ordinal, which is the only thing that
survives across the six corpus locales without a translation step.

**Radio and checkbox groups.** A shared ``name`` inside one form, which is what
makes them one control to the browser. Two members minimum: a single radio with
a unique name is a group of one, and calling it a group would put a group id on
a control that has nobody to be grouped with.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from autofill_audit.descriptors import FieldDescriptor, GroupRole
from autofill_audit.extract.signals import RawControl
from autofill_audit.taxonomy import Label

__all__ = [
    "ADDRESS_LINE_WORDS",
    "MIN_YEAR_RUN",
    "YEAR_WINDOW_BACK",
    "YEAR_WINDOW_FORWARD",
    "detect_groups",
    "is_month_options",
    "is_year_options",
]

MIN_YEAR_RUN: Final[int] = 3
"""The shortest run of consecutive years that reads as an expiry list.

Two is not enough: any pair of adjacent numbers is a run of two. Three is the
point at which "consecutive years starting near now" stops being a coincidence,
and the shortest expiry list on a real checkout is longer than that anyway."""

YEAR_WINDOW_BACK: Final[int] = 5
YEAR_WINDOW_FORWARD: Final[int] = 20
"""How far from the current year an expiry list may start.

Backwards to tolerate a page, or a committed corpus, generated a few years ago
and never regenerated. Forwards to twice the longest card term anybody issues,
because some pages pad the list. Both are relative to the year the caller passes
in, never to a literal, so nothing here expires.

The window is what separates an expiry list from every other run of consecutive
years a page might hold. A list of birth years fails it going back and fails the
ascending check going forward, which is the case worth being sure about."""

_DIGITS: Final[re.Pattern[str]] = re.compile(r"\d+")

ADDRESS_LINE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "address",
        "adresse",
        "addr",
        "street",
        "strasse",
        "straße",
        "rue",
        "line",
        "ligne",
        "zeile",
        "住所",
        "番地",
        "apt",
        "apartment",
        "suite",
        "unit",
        "wohnung",
        "appartement",
    }
)
"""Words that appear in one line of a postal address, across the corpus locales.

Not a translation table and not trying to be. It exists so that a run of three
text inputs that all say "address something" can be recognised as one address
without any of them being classified first, which is the classifier's job and
happens later."""

_ORDINALS: Final[frozenset[str]] = frozenset({"1", "2", "3", "one", "two", "three"})

_MONTH_WORDS: Final[tuple[str, ...]] = ("month", "monat", "mois", "mes", "mm", "月")
_YEAR_WORDS: Final[tuple[str, ...]] = ("year", "jahr", "annee", "année", "ano", "yy", "年")
"""Words that name half of a split expiry, across the corpus locales.

Needed because spec section 9.5 admits a pair made of a select and a text input,
and a text input has no option list to key on. Matched as a substring of a
normalised token, so ``expyear`` and ``security_expyear`` both hit ``year``
without a stemmer and without one entry per spelling."""

_TEXTUAL_EXPIRY_TYPES: Final[frozenset[str | None]] = frozenset({None, "text", "number", "tel"})

_ADDRESS_LINE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        Label.ADDRESS_LINE1.value,
        Label.ADDRESS_LINE2.value,
        Label.ADDRESS_LINE3.value,
    }
)

_MIN_RUN: Final[int] = 2
_MAX_ADDRESS_RUN: Final[int] = 3


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One control paired with the raw record it came from."""

    index: int
    descriptor: FieldDescriptor
    raw: RawControl


def _digits_of(text: str) -> int | None:
    """Return the first run of digits in ``text`` as an integer, or None."""
    match = _DIGITS.search(text)
    if match is None:
        return None
    return int(match.group())


def _sequence_one_to_twelve(values: Sequence[str]) -> bool:
    """Whether ``values`` are the numbers one to twelve, in order."""
    if len(values) != 12:
        return False
    for position, value in enumerate(values, start=1):
        stripped = value.strip()
        if not stripped.isdigit() or int(stripped) != position:
            return False
    return True


def _digit_sequence_one_to_twelve(labels: Sequence[str]) -> bool:
    """Whether the digits inside ``labels`` are one to twelve, in order.

    This is what catches ``1月`` through ``12月`` without a Japanese month
    table, and it is why the check is on digits rather than on equality.
    """
    if len(labels) != 12:
        return False
    return all(_digits_of(label) == position for position, label in enumerate(labels, start=1))


def is_month_options(
    values: Sequence[str], labels: Sequence[str], *, multiple: bool = False
) -> bool:
    """Whether a select offers the twelve months of a year.

    Exactly twelve options, and no blank first option. The corpus makes that
    discriminating on purpose: every other select it emits (country, card type,
    title, sex, administrative area) carries a blank first option, and only the
    month and year selects do not, precisely so that group detection is not
    broken corpus wide by an off-by-one.

    A multi-select is refused outright. Twelve options a user may choose several
    of is not a month picker, whatever the options say.
    """
    if multiple:
        return False
    return _sequence_one_to_twelve(values) or _digit_sequence_one_to_twelve(labels)


def _year_run(values: Sequence[str], *, now_year: int) -> bool:
    """Whether ``values`` are consecutive years starting near ``now_year``."""
    if len(values) < MIN_YEAR_RUN:
        return False
    years: list[int] = []
    for value in values:
        stripped = value.strip()
        if not stripped.isdigit():
            return False
        if len(stripped) == 4:
            years.append(int(stripped))
        elif len(stripped) == 2:
            years.append(2000 + int(stripped))
        else:
            return False
    if any(later != earlier + 1 for earlier, later in pairwise(years)):
        return False
    return now_year - YEAR_WINDOW_BACK <= years[0] <= now_year + YEAR_WINDOW_FORWARD


def is_year_options(
    values: Sequence[str], labels: Sequence[str], *, now_year: int, multiple: bool = False
) -> bool:
    """Whether a select offers a run of consecutive expiry years.

    Two digit and four digit years are both accepted, because both are common
    and the specification names both. The window is relative to ``now_year``,
    which the caller supplies; there is no default, so no test can accidentally
    depend on the machine's clock.
    """
    if multiple:
        return False
    return _year_run(values, now_year=now_year) or _year_run(labels, now_year=now_year)


def _looks_like_address_line(descriptor: FieldDescriptor) -> bool:
    """Whether one control reads as a single line of a postal address."""
    if descriptor.declared.token in _ADDRESS_LINE_TOKENS:
        return True
    if descriptor.tag != "input":
        return False
    if descriptor.input_type not in (None, "text"):
        return False
    tokens = set(descriptor.norm.label_tokens) | set(descriptor.norm.identifier_tokens)
    if not tokens & ADDRESS_LINE_WORDS:
        return False
    return bool(tokens & _ORDINALS)


def _adjacent(left: _Candidate, right: _Candidate) -> bool:
    """Whether two controls sit close enough to be one structural group.

    Same fieldset counts, and so does same immediate parent: the corpus renders
    a grouped expiry pair inside a fieldset with a legend and an ungrouped one
    as two selects sharing a single ``div``, and both are the same pair.
    """
    if left.raw.fieldset_key is not None and left.raw.fieldset_key == right.raw.fieldset_key:
        return True
    return left.raw.parent_key == right.raw.parent_key and left.raw.parent_key != ""


def _mentions(descriptor: FieldDescriptor, words: Sequence[str]) -> bool:
    """Whether any normalised token contains one of ``words``."""
    tokens = (*descriptor.norm.label_tokens, *descriptor.norm.identifier_tokens)
    return any(word in token for token in tokens for word in words)


def _is_month_half(candidate: _Candidate) -> bool:
    """Whether a control is the month half of a split expiry."""
    descriptor = candidate.descriptor
    if descriptor.tag == "select":
        return is_month_options(
            descriptor.option_values, descriptor.option_labels, multiple=candidate.raw.multiple
        )
    if descriptor.tag == "input" and descriptor.input_type in _TEXTUAL_EXPIRY_TYPES:
        return _mentions(descriptor, _MONTH_WORDS)
    return False


def _is_year_half(candidate: _Candidate, *, now_year: int) -> bool:
    """Whether a control is the year half of a split expiry."""
    descriptor = candidate.descriptor
    if descriptor.tag == "select":
        return is_year_options(
            descriptor.option_values,
            descriptor.option_labels,
            now_year=now_year,
            multiple=candidate.raw.multiple,
        )
    if descriptor.tag == "input" and descriptor.input_type in _TEXTUAL_EXPIRY_TYPES:
        return _mentions(descriptor, _YEAR_WORDS)
    return False


def _detect_expiry(
    candidates: Sequence[_Candidate], *, now_year: int
) -> dict[int, tuple[GroupRole, str]]:
    """Pair each month control with the year control beside it.

    At least one half must be a ``<select>``. That is spec section 9.5's own
    phrasing ("two adjacent select elements, or a select and a text input") and
    it is what stops the rule from firing on the hostile tier, where two
    unlabelled text inputs sit side by side with nothing to say they are an
    expiry pair. Guessing there would invent a group, which spec section 9.5 is
    explicit is the worse of the two failures.
    """
    assigned: dict[int, tuple[GroupRole, str]] = {}
    group_number = 0
    position = 0
    while position < len(candidates) - 1:
        first = candidates[position]
        second = candidates[position + 1]
        if not _adjacent(first, second) or "select" not in (
            first.descriptor.tag,
            second.descriptor.tag,
        ):
            position += 1
            continue
        if _is_month_half(first) and _is_year_half(second, now_year=now_year):
            month, year = first, second
        elif _is_year_half(first, now_year=now_year) and _is_month_half(second):
            month, year = second, first
        else:
            position += 1
            continue
        group_number += 1
        group_id = f"expiry-{group_number}"
        assigned[month.index] = (GroupRole.CC_EXP_MONTH, group_id)
        assigned[year.index] = (GroupRole.CC_EXP_YEAR, group_id)
        position += 2
    return assigned


def _detect_address_runs(candidates: Sequence[_Candidate]) -> dict[int, tuple[GroupRole, str]]:
    """Mark runs of two or three consecutive address-line controls in one form.

    Consecutive in document order and inside the same form. Not the same parent:
    every locale profile in the corpus puts each address line in its own row,
    and two of the six put the postal code in the middle of the run, so a rule
    that demanded a shared parent would find nothing anywhere.
    """
    assigned: dict[int, tuple[GroupRole, str]] = {}
    group_number = 0
    position = 0
    while position < len(candidates):
        run: list[_Candidate] = []
        cursor = position
        while cursor < len(candidates) and len(run) < _MAX_ADDRESS_RUN:
            candidate = candidates[cursor]
            if not _looks_like_address_line(candidate.descriptor):
                break
            if run and run[-1].raw.form_key != candidate.raw.form_key:
                break
            run.append(candidate)
            cursor += 1
        if len(run) >= _MIN_RUN:
            group_number += 1
            group_id = f"address-lines-{group_number}"
            for member in run:
                assigned[member.index] = (GroupRole.ADDRESS_LINE_MEMBER, group_id)
            position = cursor
            continue
        position += 1
    return assigned


def _detect_name_groups(candidates: Sequence[_Candidate]) -> dict[int, tuple[GroupRole, str]]:
    """Group radios and checkboxes that share a name inside one form."""
    assigned: dict[int, tuple[GroupRole, str]] = {}
    buckets: dict[tuple[str | None, str, str], list[_Candidate]] = {}
    for candidate in candidates:
        input_type = candidate.descriptor.input_type
        if input_type not in ("radio", "checkbox"):
            continue
        name = candidate.descriptor.name
        if not name:
            continue
        buckets.setdefault((candidate.raw.form_key, input_type, name), []).append(candidate)

    counters = {"radio": 0, "checkbox": 0}
    for key in sorted(buckets, key=lambda item: buckets[item][0].index):
        members = buckets[key]
        if len(members) < _MIN_RUN:
            continue
        input_type = key[1]
        counters[input_type] += 1
        group_id = f"{input_type}-{counters[input_type]}"
        role = GroupRole.RADIO_MEMBER if input_type == "radio" else GroupRole.CHECKBOX_MEMBER
        for member in members:
            assigned[member.index] = (role, group_id)
    return assigned


def detect_groups(
    descriptors: Sequence[FieldDescriptor], raws: Sequence[RawControl], *, now_year: int
) -> list[FieldDescriptor]:
    """Return the descriptors with any detected group membership applied.

    Runs after the walk and before nothing in particular: the descriptors are
    already complete, and this pass only ever writes ``group_role`` and
    ``group_id``. Detection order settles the one case where two rules could
    both fire, which is a split expiry pair whose labels also happen to match
    the address vocabulary. Expiry wins, because it is the more specific claim.

    Args:
        descriptors: the finished descriptors, in document order.
        raws: the raw records they were built from, in the same order.
        now_year: the year to measure an expiry window against.

    Raises:
        ValueError: if the two sequences are not the same length, which would
            mean the walk and the assembly had disagreed about how many
            controls there are.
    """
    if len(descriptors) != len(raws):
        raise ValueError(
            f"group detection needs one raw record per descriptor: "
            f"{len(descriptors)} descriptors, {len(raws)} records"
        )

    candidates = [
        _Candidate(index=index, descriptor=descriptor, raw=raw)
        for index, (descriptor, raw) in enumerate(zip(descriptors, raws, strict=True))
        if descriptor.undetectable_reason is None
    ]

    assigned: dict[int, tuple[GroupRole, str]] = {}
    assigned.update(_detect_name_groups(candidates))
    for index, value in _detect_address_runs(candidates).items():
        assigned.setdefault(index, value)
    assigned.update(_detect_expiry(candidates, now_year=now_year))

    return [
        descriptor.with_group(*assigned[index]) if index in assigned else descriptor
        for index, descriptor in enumerate(descriptors)
    ]
