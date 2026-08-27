---
name: Bug
about: Something crashed, hung, produced malformed output, or returned the wrong exit code.
title: "Bug: <one line>"
labels: bug
---

<!--
If the tool made a wrong *accusation*, please use the false positive template
instead. If it stayed silent about a broken field, use the false negative
template. This one is for everything else.

Please do not paste a real page. Reduce it to the smallest input that
reproduces the problem and replace any real values with invented ones.
-->

## What happened

## What you expected

## How to reproduce

```bash
# the exact command
```

```html
<!-- the minimal input, if a page is involved -->
```

## Output

```
paste the full output, including any traceback and the exit code from `echo $?`
```

## Environment

- `autofill-audit --version`:
- Engine (`--engine auto`, `rules`, `ngram`, or `llm`):
- Python version:
- Operating system, and whether it is a container or a subsystem:
- How it was installed (`pipx`, `pip`, from a checkout):
- Playwright and browser version, if the failure involves loading a page:
- Anything non-default in `autofill-audit.toml`:

## The exit code contract

For reference, so that a wrong exit code can be reported as one:

| Code | Meaning |
|---|---|
| `0` | The page was audited and nothing at or above the failure threshold was found |
| `1` | Findings at or above the failure threshold |
| `2` | Usage error: a bad flag, a missing argument, an unreadable config file |
| `3` | The page could not be reached or could not be loaded within the budget |
| `4` | An internal error. This one is always a bug, whatever else was going on |
