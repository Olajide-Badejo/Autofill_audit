"""Stable selector construction, per spec section 9.3.

Spec section 9.3 makes selector generation part of the corpus contract: answer
keys reference fields by selector, so a change to how selectors are built
invalidates every committed key. That makes this module a schema, not a helper,
and P2's extractor has to reproduce its output exactly rather than approximately.

The preference order, unchanged from the specification:

1. ``#id`` when the id is present, unique in the document, and does not look
   generated.
2. ``form[name="..."] [name="..."]`` when the control has a name and its form
   has a name.
3. A ``:nth-of-type`` path from the nearest stable ancestor.

Two conventions are fixed here and are used identically by the generator, by
``corpus validate``, and (from P2) by the extractor and all three renderers.

**Shadow boundaries use `` >>> ``.** The host's own selector is built by the same
preference order, then the separator, then the selector of the control inside
the shadow root, resolved relative to the shadow root.

**The second preference uses a descendant combinator, not a child combinator.**
The specification sketches it as ``form[name] > [name="..."]``, and a literal
child combinator would only ever match a control that is an immediate child of
the form element. Real pages, and every form this generator emits, wrap controls
in layout containers. Emitting a child combinator would produce selectors that
resolve to nothing, which is worse than a small deviation from a sketch.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "SHADOW_SEPARATOR",
    "form_name_selector",
    "id_selector",
    "join_shadow",
    "looks_generated",
    "nth_of_type_path",
    "nth_of_type_tail",
]

SHADOW_SEPARATOR: Final[str] = " >>> "
"""Separates a shadow host's selector from the selector of a control inside its
shadow root. Documented once here and used by every consumer."""

_DIGIT_RUN: Final[re.Pattern[str]] = re.compile(r"\d{4,}")
_HEX_RUN: Final[re.Pattern[str]] = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8,}(?![0-9a-fA-F])")


def looks_generated(identifier: str) -> bool:
    """Return True when an id looks machine-generated rather than authored.

    The test is deliberately narrow: a run of four or more digits, or a run of
    eight or more hexadecimal characters. Framework-generated ids
    (``mat-input-0a9f4c21``, ``:r7:``, ``ember1423``) carry one of those; hand
    written ids such as ``input1``, ``field_7``, and ``shipping-postcode`` do
    not, and a check that swept those up would push every hostile-tier control
    onto a positional path and stop exercising the id branch at all.
    """
    return bool(_DIGIT_RUN.search(identifier) or _HEX_RUN.search(identifier))


def id_selector(element_id: str) -> str:
    """Return the first-preference selector for an element with an id."""
    return f"#{element_id}"


def form_name_selector(form_name: str, control_name: str) -> str:
    """Return the second-preference selector, scoped to the named form."""
    return f'form[name="{form_name}"] [name="{control_name}"]'


def nth_of_type_tail(steps: tuple[tuple[str, int], ...]) -> str:
    """Return the anchorless part of a positional path.

    Split out from ``nth_of_type_path`` at P2, which needs the same tail with no
    anchor in front of it: inside a shadow root the root itself is the anchor
    and has no selector of its own, so the path begins at the first step.
    Keeping one implementation of the join is the point.
    """
    if not steps:
        raise ValueError("a positional path needs at least one step")
    return " > ".join(f"{tag}:nth-of-type({index})" for tag, index in steps)


def nth_of_type_path(anchor: str, steps: tuple[tuple[str, int], ...]) -> str:
    """Return the third-preference selector.

    ``anchor`` is the selector of the nearest stable ancestor, already built by
    one of the two preferred forms. ``steps`` walks down from it as
    ``(tag, one_based_index_among_same_tag_siblings)`` pairs.
    """
    if not steps:
        raise ValueError("a positional path needs at least one step below its anchor")
    return f"{anchor} > {nth_of_type_tail(steps)}"


def join_shadow(host_selector: str, inner_selector: str) -> str:
    """Join a host selector and a selector inside that host's shadow root."""
    return f"{host_selector}{SHADOW_SEPARATOR}{inner_selector}"
