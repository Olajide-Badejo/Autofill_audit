"""Text normalisation: NFKC, casefold, de-camelCase, token split, stopwords.

One pure function, used identically at corpus time, training time, and inference
time (spec section 9.7). Every step is exposed separately so that every step is
separately tested, and the composition is the only thing callers use.

Order, and one deliberate reading of the specification
------------------------------------------------------

Spec section 9.7 numbers the steps NFKC, casefold, de-camelCase, split, stoplist.
Taken literally, casefolding the whole string before looking for lower-to-upper
transitions destroys the very information step 3 needs: ``firstName`` casefolds
to ``firstname``, in which no boundary exists, and the specification's own
worked example (``firstName`` becomes ``first name``) becomes unreachable.

So the reading implemented here is: NFKC first, then boundary insertion, then
casefold **each resulting token**. Nothing step 2 exists for is lost, because
casefold is applied to every token and both of the properties the specification
names it for are per-character: the sharp s folds to ``ss`` and the Turkish
dotted capital I folds correctly whether it is folded before or after a boundary
is inserted beside it. What is gained is that step 3 works at all.

Casefolding is followed by a second NFKC pass on each token. That is the Unicode
recommendation for canonical caseless matching, and without it there are folded
forms that are not themselves in NFKC.

Boundary insertion then runs a **second** time, after the fold. That is not
symmetry for its own sake: case folding does not always produce lowercase, so a
folded token can still contain a case transition the first pass never saw, and
the function is not idempotent without it. ``normalize_tokens`` explains the
case that proved it.

The stoplist and why it is applied twice
----------------------------------------

Spec section 9.7 gives the framework-noise stoplist as ``ctl00``, ``ng``,
``mat``, ``mui``, ``form``, ``input``, ``field``, ``text``, and applies it **only
to the identifier stream**: a ``<label>`` that literally reads "Field" is
information about how bad the page is, and dropping it would hide that.

``ctl00`` cannot survive the letter-to-digit split, which turns it into ``ctl``
and ``00``, so a stoplist applied only after splitting would never match the one
entry on the list that names a real framework. The stoplist is therefore applied
to the delimiter-separated fragments **before** the letter-to-digit split, and
again to the finished tokens. Both passes use the same list, so there is still
exactly one place to edit it.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = [
    "FRAMEWORK_NOISE",
    "casefold_token",
    "drop_framework_noise",
    "insert_camel_boundaries",
    "insert_script_boundaries",
    "nfkc",
    "normalize_identifier_tokens",
    "normalize_text",
    "normalize_tokens",
    "split_on_delimiters",
]

FRAMEWORK_NOISE: Final[frozenset[str]] = frozenset(
    {"ctl00", "ng", "mat", "mui", "form", "input", "field", "text"}
)
"""The stoplist of spec section 9.7, verbatim. Applied to identifier tokens
only, never to label tokens."""


def _is_token_character(character: str) -> bool:
    """Whether a character belongs inside a token rather than between two.

    Alphanumerics, and **combining marks**. The marks are the part worth
    stating: Python's ``\\w`` excludes them, and a splitter built on ``\\w``
    treats every one of them as a separator. That shreds Devanagari, Thai,
    Hebrew with points, and anything in decomposed form, and it also breaks
    idempotence outright, because casefolding the Turkish dotted capital I
    produces an ``i`` followed by a combining dot: split on the dot and a second
    pass over the same text returns something different from the first.

    The underscore is deliberately not a token character. Python counts it as a
    word character and every form on the web counts it as a separator.
    """
    if character == "_":
        return False
    return character.isalnum() or unicodedata.category(character).startswith("M")


def nfkc(text: str) -> str:
    """Apply Unicode NFKC normalisation (spec section 9.7 step 1).

    First, and first for a reason: it is what makes a full-width Japanese form
    label comparable to its half-width equivalent, so every later step sees one
    spelling instead of two.
    """
    return unicodedata.normalize("NFKC", text)


def casefold_token(token: str) -> str:
    """Casefold one token and return it in NFKC (spec section 9.7 step 2).

    ``str.casefold`` rather than ``str.lower`` because casefold folds the German
    sharp s to ``ss`` and handles the Turkish dotted capital I correctly, which
    ``lower`` does not. The trailing NFKC is the canonical caseless matching
    recommendation and is what makes the whole function idempotent.
    """
    return unicodedata.normalize("NFKC", token.casefold())


def _is_letter(character: str) -> bool:
    """True for a Unicode letter."""
    return unicodedata.category(character).startswith("L")


def _is_digit(character: str) -> bool:
    """True for a Unicode decimal digit."""
    return character.isdigit()


def _is_upper(character: str) -> bool:
    """True for a character whose case is upper."""
    return character.isupper()


def _is_lower(character: str) -> bool:
    """True for a character whose case is lower."""
    return character.islower()


def insert_camel_boundaries(text: str) -> str:
    """Insert spaces at case and letter-to-digit transitions (step 3).

    ``firstName`` becomes ``first Name`` and ``addr1`` becomes ``addr 1``. A run
    of capitals followed by a lowercase letter splits before the last capital,
    so ``ZIPCode`` becomes ``ZIP Code`` rather than ``Z I P Code``: acronyms are
    common in form identifiers and shredding them into single letters would put
    noise into every token stream that contains one.
    """
    if not text:
        return text
    pieces: list[str] = [text[0]]
    for index in range(1, len(text)):
        previous = text[index - 1]
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        boundary = False
        if (
            (_is_lower(previous) and _is_upper(current))
            or (_is_upper(previous) and _is_upper(current) and _is_lower(following))
            or (_is_letter(previous) and _is_digit(current))
            or (_is_digit(previous) and _is_letter(current))
        ):
            boundary = True
        if boundary:
            pieces.append(" ")
        pieces.append(current)
    return "".join(pieces)


def _script_of(character: str) -> str:
    """Classify a character into the coarse script classes step 4 splits on.

    Only the Latin-to-CJK boundary is a split point, so Han, hiragana,
    katakana, and hangul share one class. Splitting Japanese into its three
    scripts would fragment ordinary labels such as the honorific prefix on a
    name field, which is the opposite of what the step is for.
    """
    code = ord(character)
    if (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xAC00 <= code <= 0xD7AF
        or 0x1100 <= code <= 0x11FF
    ):
        return "cjk"
    if _is_letter(character):
        return "latin"
    return "other"


def insert_script_boundaries(text: str) -> str:
    """Insert spaces where the script changes between Latin and CJK (step 4).

    ``郵便番号zipcode`` yields both tokens instead of one that matches nothing.
    """
    if not text:
        return text
    pieces: list[str] = [text[0]]
    previous_script = _script_of(text[0])
    for character in text[1:]:
        script = _script_of(character)
        if (
            script != previous_script
            and script in {"latin", "cjk"}
            and previous_script in {"latin", "cjk"}
        ):
            pieces.append(" ")
        pieces.append(character)
        previous_script = script
    return "".join(pieces)


def split_on_delimiters(text: str) -> list[str]:
    """Split on every character that is not part of a word (step 4).

    "Part of a word" is alphanumerics plus combining marks; see
    ``_is_token_character`` for why the marks have to be in there. Underscores
    are delimiters even though Python calls them word characters, because
    ``field_7`` is two tokens in every form on the web.
    """
    tokens: list[str] = []
    current: list[str] = []
    for character in text:
        if _is_token_character(character):
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def drop_framework_noise(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Drop pure framework noise (step 5). Identifier stream only."""
    return tuple(token for token in tokens if token not in FRAMEWORK_NOISE)


def _boundaries(text: str) -> str:
    """Insert every boundary of steps 3 and 4."""
    return insert_script_boundaries(insert_camel_boundaries(text))


def normalize_tokens(raw: str) -> tuple[str, ...]:
    """Normalise one raw string into tokens (spec section 9.7).

    The stoplist is deliberately *not* applied here. This is the function label
    and context text go through, and spec section 9.7 restricts the stoplist to
    the identifier stream. ``normalize_identifier_tokens`` is the variant that
    applies it.

    **Boundaries are inserted twice, once before folding and once after.** The
    second pass is not belt and braces; without it the function is not
    idempotent, and it took a property test to find out why.

    Case folding does not always produce lowercase. Cherokee folds the other
    way, to uppercase, so folding an ``A`` beside a Cherokee capital yields a
    lowercase ``a`` beside that same capital, which still holds a
    lower-to-upper transition that the first boundary pass never saw. Feed that
    output back in and it splits into two tokens, which is a different answer
    from the first. The same argument applies to the script boundary: the NFKC
    inside the fold can turn a compatibility character into ideographs and put a
    Latin-to-CJK boundary inside a token that did not have one.

    Folding after boundary insertion is itself required, because folding first
    destroys the case information step 3 needs; see the module docstring. So the
    only order that satisfies both constraints is to bracket the fold.
    """
    tokens: list[str] = []
    for piece in split_on_delimiters(_boundaries(nfkc(raw))):
        folded = casefold_token(piece)
        tokens.extend(part for part in split_on_delimiters(_boundaries(folded)) if part)
    return tuple(tokens)


def normalize_text(raw: str) -> str:
    """Normalise and re-join, so that idempotence can be stated as an equality."""
    return " ".join(normalize_tokens(raw))


def normalize_identifier_tokens(raw: str) -> tuple[str, ...]:
    """Normalise an identifier and apply the framework stoplist (step 5).

    The pre-split pass is what lets ``ctl00`` on the stoplist match the
    ``ctl00`` in ``ctl00$txt3``; see the module docstring.
    """
    prepared = nfkc(raw)
    survivors = [
        fragment
        for fragment in split_on_delimiters(prepared)
        if casefold_token(fragment) not in FRAMEWORK_NOISE
    ]
    tokens: list[str] = []
    for fragment in survivors:
        tokens.extend(normalize_tokens(fragment))
    return drop_framework_noise(tuple(tokens))
