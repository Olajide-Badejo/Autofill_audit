---
name: False positive
about: The tool accused a field it should not have. This is the most important report we get.
title: "False positive: CODE on <one line about the field>"
labels: false-positive
---

<!--
This is the report that matters most. The output of this tool is a list of
accusations about somebody else's markup, and a wrong finding costs a developer
time and costs this project its credibility. Thank you for taking the trouble.

Please do not paste a real page. Reduce it to the smallest markup that still
produces the wrong finding, and replace any real names, addresses, phone
numbers, emails or card numbers with obviously invented ones. This repository
carries no personal data, including the author's own, and we cannot accept a
report that would put some in it.
-->

## The finding

Which code, on which control, and what the tool said.

```
paste the relevant lines of the report here, including the evidence list
and the confidence or rule tier
```

## The markup that produces it

Minimal, self-contained, and with invented values.

```html
<!-- paste here -->
```

## Why it is wrong

What the field actually is, and what the correct answer would have been.
`UNKNOWN` is a correct answer when the evidence genuinely does not decide, and
saying so is useful.

## Environment

- `autofill-audit --version`:
- Engine (`--engine auto`, `rules`, `ngram`, or `llm`):
- Operating system:
- Anything non-default in `autofill-audit.toml`:

## Anything else

If the same markup produces a different result under a different engine, that is
worth saying: the three engines speak under different rules about when to speak,
and a disagreement between them is itself informative.
