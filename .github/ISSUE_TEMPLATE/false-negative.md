---
name: False negative
about: A field that will not autofill, and the tool said nothing about it.
title: "False negative: <one line about the field>"
labels: false-negative
---

<!--
Please do not paste a real page. Reduce it to the smallest markup that still
reproduces the silence, and replace any real names, addresses, phone numbers,
emails or card numbers with obviously invented ones.
-->

## The field the tool missed

What the control is, and which finding you expected.

## The markup

Minimal, self-contained, and with invented values.

```html
<!-- paste here -->
```

## What the tool printed

```
paste the report, or say "nothing above the failure threshold"
```

## Environment

- `autofill-audit --version`:
- Engine (`--engine auto`, `rules`, `ngram`, or `llm`):
- Operating system:
- Anything non-default in `autofill-audit.toml`:

## Before you file

Two silences are deliberate rather than defects, and it saves everyone time to
rule them out first.

**Abstention is an answer.** When the evidence does not decide, the tool says
`UNKNOWN` or emits `LOW_CONFIDENCE` rather than guessing. On the rule engine that
happens whenever two labels tie at the same tier, which is common and correct:
several languages use one phrase for two different address fields. If the
evidence in your snippet genuinely does not distinguish two labels, silence is
the right output and the interesting question is whether a signal exists that
would break the tie.

**Some things are invisible on purpose.** Closed shadow roots, cross-origin
frames, canvas-rendered widgets and the steps of a multi-step form that are not
in the document are reported as undetectable rather than guessed at. Those are
boundaries, and they are listed in the README.
