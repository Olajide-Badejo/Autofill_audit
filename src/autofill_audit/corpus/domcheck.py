"""A very small HTML tree and CSS-subset resolver, for checking our own output.

This exists for one reason: an answer key whose selectors do not resolve is
worse than no answer key, because every downstream measurement silently loses
the fields it could not find, and the loss looks like a classifier failure. The
generator therefore checks its own selectors before writing them, and
``corpus validate`` checks them again on disk.

It would be possible to do this with a browser, and P2 has one. Requiring a
browser to validate a corpus would mean the corpus could not be validated in the
reachability job, could not be validated without Chromium installed, and would
couple P1's gate to P2's dependency. The subset of CSS this generator emits is
small and fully known, so a resolver for exactly that subset is a few dozen
lines and has no dependencies at all.

**Supported selector subset**, which is exactly what ``selectors.py`` emits:
``#id``, ``tag``, ``[attr="value"]``, ``tag[attr="value"]``,
``tag:nth-of-type(n)``, the child combinator ``>``, and the descendant
combinator (a space). Anything else raises rather than silently matching
nothing, because a resolver that quietly returns an empty list when it does not
understand a selector is a checker that passes when it should fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final

__all__ = [
    "CONTROL_TAGS",
    "Element",
    "count_controls",
    "parse",
    "resolve",
]

_VOID_TAGS: Final[frozenset[str]] = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)

CONTROL_TAGS: Final[frozenset[str]] = frozenset({"input", "select", "textarea"})
"""The tags that count as form controls for the generator's completeness
assertion. Matches the extractor's own definition in spec section 9.1, minus the
ARIA and contenteditable cases, which this generator never emits."""

_NON_CONTROL_INPUT_TYPES: Final[frozenset[str]] = frozenset(
    {"hidden", "submit", "button", "image", "reset"}
)

_SIMPLE_STEP: Final[re.Pattern[str]] = re.compile(
    r"""^
    (?:\#(?P<id>[A-Za-z0-9_\-]+))?
    (?P<tag>[A-Za-z][A-Za-z0-9\-]*)?
    (?:\[(?P<attr>[A-Za-z\-]+)="(?P<value>[^"]*)"\])?
    (?::nth-of-type\((?P<nth>\d+)\))?
    $""",
    re.VERBOSE,
)


@dataclass(slots=True, eq=False)
class Element:
    """One element in a parsed document.

    ``eq=False`` is load bearing. A generated ``__eq__`` compares every field,
    ``parent`` points back up the tree, and comparing two elements would recurse
    until the stack ran out. Elements are identity objects: two of them are the
    same element when they are the same object, which is also exactly what
    ``list.index`` needs while resolving ``:nth-of-type``.
    """

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element] = field(default_factory=list)
    parent: Element | None = None
    text: str = ""

    def descendants(self) -> list[Element]:
        """Every element below this one, in document order."""
        out: list[Element] = []
        for child in self.children:
            out.append(child)
            out.extend(child.descendants())
        return out


class _TreeBuilder(HTMLParser):
    """Builds an ``Element`` tree. Tolerant, because the corpus is well formed
    and a tolerant parser keeps the failure modes in one place."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element(tag="#document")
        self._stack: list[Element] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(
            tag=tag,
            attrs={key: (value if value is not None else "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(element)
        if tag not in _VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(
            tag=tag,
            attrs={key: (value if value is not None else "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(element)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if len(self._stack) > 1:
            self._stack[-1].text += data


def parse(html: str) -> Element:
    """Parse a document into an element tree rooted at a synthetic node."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _matches(element: Element, step: str) -> bool:
    match = _SIMPLE_STEP.match(step)
    if match is None:
        raise ValueError(f"unsupported selector step {step!r}")
    groups = match.groupdict()
    if not any(groups.values()):
        raise ValueError(f"unsupported selector step {step!r}")
    if groups["id"] is not None and element.attrs.get("id") != groups["id"]:
        return False
    if groups["tag"] is not None and element.tag != groups["tag"]:
        return False
    if groups["attr"] is not None and element.attrs.get(groups["attr"]) != groups["value"]:
        return False
    if groups["nth"] is not None:
        parent = element.parent
        if parent is None:
            return False
        same_tag = [child for child in parent.children if child.tag == element.tag]
        if same_tag.index(element) + 1 != int(groups["nth"]):
            return False
    return True


def _split_steps(selector: str) -> list[tuple[str, str]]:
    """Split a selector into ``(combinator, step)`` pairs.

    The first pair's combinator is ``" "`` and is not used: the first step is
    matched against every element in the document.
    """
    tokens = selector.replace(" > ", " \x00 ").split()
    pairs: list[tuple[str, str]] = []
    combinator = " "
    for token in tokens:
        if token == "\x00":
            combinator = ">"
            continue
        pairs.append((combinator, token))
        combinator = " "
    if not pairs:
        raise ValueError(f"empty selector {selector!r}")
    return pairs


def resolve(root: Element, selector: str) -> list[Element]:
    """Return every element matching ``selector``, in document order.

    Raises:
        ValueError: when the selector uses syntax outside the supported subset.
    """
    pairs = _split_steps(selector)
    _, first = pairs[0]
    current = [element for element in root.descendants() if _matches(element, first)]
    for combinator, step in pairs[1:]:
        nxt: list[Element] = []
        for element in current:
            candidates = element.children if combinator == ">" else element.descendants()
            nxt.extend(child for child in candidates if _matches(child, step))
        current = nxt
    return current


def count_controls(root: Element) -> int:
    """Count the form controls a walker would emit a descriptor for.

    Hidden, submit, button, image, and reset inputs are excluded, matching the
    walker's rule in spec section 9.1.
    """
    total = 0
    for element in root.descendants():
        if element.tag not in CONTROL_TAGS:
            continue
        if element.tag == "input":
            input_type = element.attrs.get("type", "text").casefold()
            if input_type in _NON_CONTROL_INPUT_TYPES:
                continue
        total += 1
    return total
