"""Stable selector construction for extracted controls (spec section 9.3).

Selector generation is part of the corpus contract: every committed answer key
references its fields by selector, so a change here invalidates them all. That
is why the primitives come from :mod:`autofill_audit.corpus.selectors` rather
than being written a second time. Two implementations of one schema drift, and
the drift would be invisible until a P4 evaluation run silently scored the wrong
fields.

What this module adds on top of the primitives is the part that needs a
document: deciding which preference applies, and building the positional path
from the right anchor.

The preference order (spec section 9.3, P1's committed reading)
---------------------------------------------------------------

1. ``#id`` when the id is present, unique within its own root, and does not look
   generated.
2. ``form[name="..."] [name="..."]`` when the control has a name, its form has a
   name, and no other control in that form shares the name. The last condition
   is not in the specification sketch and has to be there: every member of a
   radio group shares one name, so without it a group of four radios would get
   one selector four times.
3. A ``:nth-of-type`` path from the nearest stable ancestor, where "stable"
   means an ancestor that preference 1 or preference 2 could address on its own.
   With no such ancestor the path is anchored at ``html``, which always exists.

**Preference 2 uses a descendant combinator.** Spec section 9.3 sketches it with
a child combinator, and P1 committed the descendant form because every form the
generator emits wraps its controls in layout containers, so a literal child
combinator would produce selectors that resolve to nothing. The extractor has to
match what the answer keys contain.

Boundary separators
-------------------

``#host >>> input:nth-of-type(1)`` for a shadow boundary and
``frame[#pay] >> #card`` for a frame boundary, both with single spaces either
side. They are stated once in ``docs/findings.md`` and used identically by every
renderer (spec section 9.3). The shadow separator is imported from the corpus
module that defines it; the frame separator is defined here because P1 had no
frames to name one for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from autofill_audit.corpus.selectors import (
    SHADOW_SEPARATOR,
    form_name_selector,
    id_selector,
    looks_generated,
    nth_of_type_path,
    nth_of_type_tail,
)

__all__ = [
    "DOCUMENT_ANCHOR",
    "FRAME_SEPARATOR",
    "SHADOW_SEPARATOR",
    "ChainStep",
    "SelectorChoice",
    "frame_token",
    "join_frames",
    "join_shadow_path",
    "selector_for_chain",
]

FRAME_SEPARATOR: Final[str] = " >> "
"""Separates a frame's own token from a selector inside that frame."""

DOCUMENT_ANCHOR: Final[str] = "html"
"""The anchor of last resort. Every document has exactly one, so a positional
path can always be built even for a page with no form, no ids, and no names."""


@dataclass(frozen=True, slots=True)
class ChainStep:
    """One element on the path from a root to a control.

    ``nth`` is the one-based index among preceding siblings **of the same tag**,
    which is what ``:nth-of-type`` counts. That detail matters on the mixed
    markup tier, where clean sections render as ``<section>`` and hostile
    sections render as ``<div>`` inside one form: the two are indexed
    independently, and an implementation that counted all siblings would
    disagree with every answer key on those forms.
    """

    tag: str
    nth: int
    element_id: str | None = None
    id_unique: bool = False
    form_name: str | None = None

    @property
    def addressable_id(self) -> str | None:
        """The id this step can be addressed by, or None."""
        if self.element_id is None or not self.id_unique:
            return None
        if looks_generated(self.element_id):
            return None
        return self.element_id


@dataclass(frozen=True, slots=True)
class SelectorChoice:
    """A selector and the preference that produced it.

    The strategy name is the vocabulary P1's answer keys already use in
    ``provenance.selector_strategy``, so a reconciliation between an extraction
    and a key can compare them directly.
    """

    selector: str
    strategy: str


def _nearest_named_form(chain: Sequence[ChainStep]) -> tuple[int, str] | None:
    """Return the index and name of the nearest ancestor form that has a name."""
    for index in range(len(chain) - 1, -1, -1):
        step = chain[index]
        if step.tag == "form" and step.form_name:
            return index, step.form_name
    return None


def _positional(chain: Sequence[ChainStep], *, start: int, anchor: str) -> str:
    """Build a positional path for ``chain[start:]`` below ``anchor``."""
    steps = tuple((step.tag, step.nth) for step in chain[start:])
    if not anchor:
        return nth_of_type_tail(steps)
    return nth_of_type_path(anchor, steps)


def selector_for_chain(
    chain: Sequence[ChainStep],
    *,
    name: str | None = None,
    name_unique_in_form: bool = False,
    root_anchor: str = DOCUMENT_ANCHOR,
) -> SelectorChoice:
    """Apply the preference order to one control.

    Args:
        chain: the elements from the top of the control's own root down to the
            control itself, inclusive. For a document root the chain starts at
            ``<body>``, because ``html`` is the anchor rather than a step. For a
            shadow root it starts at the root's first element child.
        name: the control's ``name`` attribute.
        name_unique_in_form: whether the control is the only one in its form
            carrying that name.
        root_anchor: ``html`` for a document, the empty string inside a shadow
            root, where the root itself is the anchor and has no selector.

    Raises:
        ValueError: if the chain is empty. A control always has at least itself.
    """
    if not chain:
        raise ValueError("a control needs at least one chain step, its own")

    target = chain[-1]
    own_id = target.addressable_id
    if own_id is not None:
        return SelectorChoice(id_selector(own_id), "id")

    named_form = _nearest_named_form(chain[:-1])
    if name and name_unique_in_form and named_form is not None:
        return SelectorChoice(form_name_selector(named_form[1], name), "form_name")

    for index in range(len(chain) - 2, -1, -1):
        ancestor_id = chain[index].addressable_id
        if ancestor_id is not None:
            return SelectorChoice(
                _positional(chain, start=index + 1, anchor=id_selector(ancestor_id)),
                "nth_of_type",
            )

    if named_form is not None:
        form_index, form_name = named_form
        anchor = f'form[name="{form_name}"]'
        return SelectorChoice(
            _positional(chain, start=form_index + 1, anchor=anchor), "nth_of_type"
        )

    return SelectorChoice(_positional(chain, start=0, anchor=root_anchor), "nth_of_type")


def join_shadow_path(host_selectors: Sequence[str], inner: str) -> str:
    """Join a chain of shadow host selectors and the selector inside the last root."""
    return SHADOW_SEPARATOR.join((*host_selectors, inner))


def frame_token(frame_selector: str) -> str:
    """Wrap a frame's own selector into the frame path token of spec section 9.3."""
    return f"frame[{frame_selector}]"


def join_frames(frame_path: Sequence[str], inner: str) -> str:
    """Prefix a selector with the frame path it lives behind."""
    if not frame_path:
        return inner
    return FRAME_SEPARATOR.join((*frame_path, inner))
