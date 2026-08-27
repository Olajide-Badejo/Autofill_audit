#!/usr/bin/env python3
"""Render the README's demo animation from a real run against a committed fixture.

Spec section 21 asks for a demo above the fold, produced from a committed
fixture so that it is reproducible: the terminal running the tool, findings
appearing, exit code shown. Regenerate rather than hand edit.

Why this renders frames rather than recording a terminal
--------------------------------------------------------

A terminal recorder captures wall clock timings, so two runs of the same command
produce two different artefacts and the committed GIF can never be reproduced
byte for byte. It also adds a binary that is not in the lock file to the set of
things a contributor needs before they can regenerate a committed asset.

This script instead takes the **real output of a real run**, which
``make_demo_gif.sh`` captures by invoking the tool against
``tests/fixtures/checkout_hostile.html``, and renders it as a typed transcript.
Nothing in the frames is written by hand: the transcript is the process's own
stdout and the exit status is the process's own exit status. The animation is a
deterministic function of that text, so the same input produces the same bytes.

The colouring is applied here rather than captured, because the terminal library
emits colour only to a real terminal and re-implementing its escape sequence
grammar to recover four highlight colours would be more code than the highlights
are worth. The mapping is small, explicit and visible in ``PALETTE`` below.

Usage:
    make_demo_gif.py --transcript FILE --exit-code N --out FILE [--rows N]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

FONT_DIRECTORY = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
FONT_REGULAR = FONT_DIRECTORY / "DejaVuSansMono.ttf"
FONT_BOLD = FONT_DIRECTORY / "DejaVuSansMono-Bold.ttf"

BACKGROUND = (24, 26, 30)
FOREGROUND = (214, 216, 220)
DIM = (128, 132, 140)

PALETTE: dict[str, tuple[int, int, int]] = {
    "prompt": (126, 196, 130),
    "critical": (226, 116, 110),
    "warning": (222, 178, 96),
    "info": (120, 168, 220),
    "code": (226, 116, 110),
    "attribute": (150, 200, 236),
}

_SEVERITY_RE = re.compile(r"^(critical|warning|info|note)\b")
# A finding code, which always carries an underscore. Requiring one keeps the
# rule engine's confidence tiers, which are single uppercase words, out of the
# colour reserved for accusations.
_FINDING_CODE_RE = re.compile(r"\b[A-Z]+_[A-Z_]+\b")
_ATTRIBUTE_RE = re.compile(r'autocomplete="[^"]*"')
_PROMPT_RE = re.compile(r"^\$ ")


def _span_colour(line: str, index: int) -> tuple[int, int, int]:
    """Colour for one character, from the small explicit mapping above."""
    if _PROMPT_RE.match(line):
        return PALETTE["prompt"]
    severity = _SEVERITY_RE.match(line)
    if severity:
        return PALETTE.get(severity.group(1), FOREGROUND)
    for match in _FINDING_CODE_RE.finditer(line):
        if match.start() <= index < match.end():
            return PALETTE["code"]
    for match in _ATTRIBUTE_RE.finditer(line):
        if match.start() <= index < match.end():
            return PALETTE["attribute"]
    if line.strip().startswith(("evidence:", "─")):
        return DIM
    return FOREGROUND


def _bold(line: str) -> bool:
    """Whether a whole line is set bold."""
    return bool(_PROMPT_RE.match(line) or _SEVERITY_RE.match(line))


def render(lines: Sequence[str], rows: int, columns: int) -> list[Image.Image]:
    """Render one frame per revealed line, plus a hold at the end."""
    regular = ImageFont.truetype(str(FONT_REGULAR), 13)
    bold = ImageFont.truetype(str(FONT_BOLD), 13)
    advance = regular.getlength("M")
    line_height = 17
    margin = 12
    width = int(advance * columns) + margin * 2
    height = line_height * rows + margin * 2

    frames: list[Image.Image] = []
    for revealed in range(1, len(lines) + 1):
        image = Image.new("RGB", (width, height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        window = lines[max(0, revealed - rows) : revealed]
        for row, line in enumerate(window):
            face = bold if _bold(line) else regular
            for index, character in enumerate(line[:columns]):
                if character == " ":
                    continue
                draw.text(
                    (margin + index * advance, margin + row * line_height),
                    character,
                    font=face,
                    fill=_span_colour(line, index),
                )
        frames.append(image.quantize(colors=16, method=Image.Quantize.MEDIANCUT))
    return frames


def build(transcript: Path, exit_code: int, out: Path, rows: int, columns: int) -> Path:
    """Assemble the animation and write it."""
    body = transcript.read_text(encoding="utf-8").rstrip("\n").splitlines()
    lines = [
        "$ autofill-audit audit tests/fixtures/checkout_hostile.html",
        *body,
        "",
        "$ echo $?",
        str(exit_code),
    ]
    frames = render(lines, rows=rows, columns=columns)
    # A short step per line so the whole thing reads in a few seconds, then a
    # long hold on the last frame so a reader who arrives mid loop sees the
    # finished screen rather than a fragment.
    durations = [110] * (len(frames) - 1) + [4000]
    # disposal=1 leaves each frame on screen and lets the encoder store only the
    # rectangle that changed. Every frame here adds one line at the bottom of a
    # screen tall enough not to scroll, so the stored rectangle is one line high
    # and the file is a fraction of what a full redraw per frame would cost.
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Render the demo and report the size, which has a budget."""
    parser = argparse.ArgumentParser(description="Render the README demo animation.")
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    # Tall enough that the transcript never scrolls, which is what lets every
    # frame store only the line it added. See the disposal note in build().
    parser.add_argument("--rows", type=int, default=int(os.environ.get("DEMO_ROWS", "30")))
    parser.add_argument("--columns", type=int, default=int(os.environ.get("DEMO_COLUMNS", "84")))
    args = parser.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = build(args.transcript, args.exit_code, args.out, args.rows, args.columns)
    size = written.stat().st_size
    print(f"make_demo_gif: wrote {written} ({size} bytes)")
    if size > 400_000:
        print(
            "make_demo_gif: over the size budget; reduce --rows or trim the transcript",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
