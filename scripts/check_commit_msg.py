#!/usr/bin/env python3
"""Ground rule 13 at the commit boundary: clean dashes, no attribution artifacts.

Runs as a ``commit-msg`` hook. It rejects a commit message that contains U+2014
or U+2013, and it rejects the attribution artifacts that tooling likes to append
to messages: generation phrases, co-author trailers, and the names of authoring
assistants.

The rejection patterns are stored base64 encoded rather than as plain source
strings. This is not obfuscation for its own sake: the repository forbids those
strings everywhere, and a plain-text blocklist would be the one file in the tree
carrying every one of them. The same reasoning puts ``chr(0x2014)`` rather than
a literal in ``scripts/check_dashes.py``.

Git's own comment lines (leading ``#``) and everything after the scissors line
are ignored, because neither reaches the stored commit message.

Usage:
    check_commit_msg.py PATH_TO_COMMIT_MSG_FILE

Exit status is 0 when the message is acceptable and 1 otherwise.
"""

from __future__ import annotations

import base64
import re
import sys
from collections.abc import Sequence
from pathlib import Path

_ENCODED_PATTERNS = (
    "Z2VuZXJhdGVkXHMrd2l0aAlhbiBhdHRyaWJ1dGlvbiBwaHJhc2UKZ2VuZXJhdGVkXHMrYnlc"
    "cysoPzphbj9ccyspPyg/OmFpfGFzc2lzdGFudHxtb2RlbHxhZ2VudCkJYW4gYXR0cmlidXRp"
    "b24gcGhyYXNlCndyaXR0ZW5ccytieVxzKyg/OmFuP1xzKyk/KD86YWl8YXNzaXN0YW50fG1v"
    "ZGVsfGFnZW50KQlhbiBhdHRyaWJ1dGlvbiBwaHJhc2UKXGJhaVstXHNdZ2VuZXJhdGVkXGIJ"
    "YW4gYXR0cmlidXRpb24gcGhyYXNlCmNvLT9hdXRob3JlZC1ieVxzKjoJYSBjby1hdXRob3Ig"
    "dHJhaWxlcgpcYmFpXHMrYXNzaXN0YW50XGIJYW4gYXNzaXN0YW50IHJlZmVyZW5jZQpcYmFz"
    "c2lzdGFudFxiCWFuIGFzc2lzdGFudCByZWZlcmVuY2UKXGJjbGF1ZGVcYglhbiBhc3Npc3Rh"
    "bnQgdmVuZG9yIG5hbWUKXGJhbnRocm9waWNcYglhbiBhc3Npc3RhbnQgdmVuZG9yIG5hbWUK"
    "XGJjaGF0Z3B0XGIJYW4gYXNzaXN0YW50IHZlbmRvciBuYW1lClxiY29waWxvdFxiCWFuIGFz"
    "c2lzdGFudCB2ZW5kb3IgbmFtZQpcYmdlbWluaVxiCWFuIGFzc2lzdGFudCB2ZW5kb3IgbmFt"
    "ZQ=="
)


def _load_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Decode the blocklist into compiled, case-insensitive patterns."""
    payload = base64.b64decode(_ENCODED_PATTERNS).decode("utf-8")
    patterns: list[tuple[re.Pattern[str], str]] = []
    for line in payload.splitlines():
        expression, _, description = line.partition("\t")
        patterns.append((re.compile(expression, re.IGNORECASE), description))
    return patterns


ATTRIBUTION_PATTERNS: list[tuple[re.Pattern[str], str]] = _load_patterns()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
_DASH_RE = re.compile(f"[{EN_DASH}{EM_DASH}]")
_DASH_NAMES = {EM_DASH: "U+2014 em dash", EN_DASH: "U+2013 en dash"}

_SCISSORS_RE = re.compile(r"^\s*#\s*-+\s*>8\s*-+")


def message_body(raw: str) -> str:
    """Strip git comment lines and anything below the scissors line."""
    kept: list[str] = []
    for line in raw.splitlines():
        if _SCISSORS_RE.match(line):
            break
        if line.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def check_message(raw: str) -> list[str]:
    """Return one human-readable reason per problem, empty when the message is fine."""
    body = message_body(raw)
    reasons: list[str] = []

    seen_dashes: set[str] = set()
    for match in _DASH_RE.finditer(body):
        character = match.group()
        if character not in seen_dashes:
            seen_dashes.add(character)
            reasons.append(
                f"the message contains a forbidden {_DASH_NAMES[character]}; "
                "use a comma, a colon, parentheses, a plain hyphen, or the word 'to'"
            )

    for pattern, description in ATTRIBUTION_PATTERNS:
        match = pattern.search(body)
        if match is not None:
            reasons.append(
                f"the message contains {description} ({match.group().strip()!r}); "
                "commit messages carry no attribution of any kind"
            )
    return reasons


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check over the commit message file named on the command line."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_commit_msg.py PATH_TO_COMMIT_MSG_FILE", file=sys.stderr)
        return 1

    path = Path(args[0])
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"check_commit_msg: cannot read {path}: {error}", file=sys.stderr)
        return 1

    reasons = check_message(raw)
    if reasons:
        print("check_commit_msg: commit message rejected", file=sys.stderr)
        for reason in reasons:
            print(f"  {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
