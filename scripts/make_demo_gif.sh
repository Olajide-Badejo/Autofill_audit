#!/usr/bin/env bash
# Regenerate the README's demo animation from a committed fixture.
#
# Spec section 21: the demo is produced from a committed fixture so that it is
# reproducible, and it is regenerated rather than hand edited. Nothing in the
# animation is written by hand. This script runs the tool for real, captures its
# stdout and its exit status, and hands both to the renderer.
#
#     scripts/make_demo_gif.sh
#
# Environment:
#     PYTHON        interpreter to use (default: the project venv)
#     DEMO_ENGINE   engine to demonstrate (default: rules)
#     DEMO_LINES    transcript lines to keep before the exit code (default: 24)
#
# The rule engine is the default here rather than the strongest engine that
# loads, and the reason is honesty rather than preference: a published wheel
# carries no model, so the rule engine is what a reader who installs the tool in
# the next five minutes will actually see.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

PYTHON="${PYTHON:-$HOME/.venvs/autofill-audit/bin/python}"
DEMO_ENGINE="${DEMO_ENGINE:-rules}"
DEMO_LINES="${DEMO_LINES:-22}"

fixture="tests/fixtures/checkout_hostile.html"
out="docs/assets/demo.gif"
transcript="$(mktemp)"
trap 'rm -f "$transcript"' EXIT

test -f "$fixture" || { echo "make_demo_gif: missing fixture $fixture" >&2; exit 1; }

status=0
COLUMNS=84 "$PYTHON" -m autofill_audit.cli audit "$fixture" \
  --engine "$DEMO_ENGINE" > "$transcript" 2>&1 || status=$?

# The fixture is deliberately broken, so a clean exit means the tool stopped
# finding what it is meant to find and the demo would be advertising a defect.
if [ "$status" -eq 0 ]; then
  echo "make_demo_gif: the hostile fixture produced no findings, which is a defect" >&2
  exit 1
fi

# The transcript is the tool's own output. Only its length is edited, because a
# demo above the fold has to fit above the fold; the trim is marked on screen so
# that nobody reads the shortened list as the whole report.
trimmed="$(mktemp)"
trap 'rm -f "$transcript" "$trimmed"' EXIT
head -n "$DEMO_LINES" "$transcript" > "$trimmed"
total="$(wc -l < "$transcript")"
remaining=$((total - DEMO_LINES))
if [ "$remaining" -gt 0 ]; then
  printf '  ... %d more lines of findings, trimmed for this animation\n' "$remaining" >> "$trimmed"
fi

"$PYTHON" scripts/make_demo_gif.py \
  --transcript "$trimmed" \
  --exit-code "$status" \
  --out "$out"

echo "make_demo_gif: regenerated $out from $fixture with the $DEMO_ENGINE engine"
