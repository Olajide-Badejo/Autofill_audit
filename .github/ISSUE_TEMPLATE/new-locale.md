---
name: New locale
about: Propose a locale the corpus and the rule vocabulary do not cover.
title: "Locale: <language tag>"
labels: locale
---

<!--
Read this first, because adding a locale is a phase rather than a pull request
and the sequencing matters.

A locale changes the generated corpus. A changed corpus changes the corpus
manifest digest, which invalidates the descriptor cache, the trained model, its
vocabulary, its calibration, both derived decision thresholds, every metric in
the model card, and both engines' test-split numbers. None of that is a
regression and all of it has to be predicted in writing before it happens,
because this repository forbids unexplained baseline drift.

So this issue is where the sequencing gets worked out. Please do not open a pull
request that adds a locale directory.
-->

## The locale

Language tag (for example `es-ES`, `pt-BR`, `ar-EG`, `hi-IN`):

Why this one? What does it exercise that the six present locales do not? Right to
left, a non-Latin script, a different address grammar, a name that decomposes
differently, a postal code that is frequently absent, and so on.

## Interface vocabulary

This is the part no value provider library can supply and the part that is
genuinely hand written. What does a form in this locale actually *say*?

| Field | Label text | Common placeholder | Common `name` or `id` |
|---|---|---|---|
| Given name | | | |
| Family name | | | |
| Street address | | | |
| Address line 2 | | | |
| City or locality | | | |
| Administrative area | | | |
| Postal code | | | |
| Country | | | |
| Telephone | | | |
| Email | | | |
| Card number | | | |
| Cardholder name | | | |
| Security code | | | |

Add rows for anything this locale has that the table does not, and delete rows
for anything it does not have. Two of the present locales have no administrative
area field at all, and that absence is part of the profile rather than an
omission.

## Address and name structure

- Which slots exist, and in what order do they appear on a form?
- Does the postal code come before or after the locality?
- Is any slot optional, and roughly how often is it absent? (A presence
  probability is more honest than a flat yes or no.)
- How does a personal name decompose? Are there additional given names, an
  honorific, a suffix, or a second script form such as a phonetic reading?

## Ambiguities

**This is the most useful section.** Which two labels does this language write
with the same or nearly the same phrase? The rule engine is designed to tie
deliberately in exactly those cases and fall through to `UNKNOWN` rather than
pick a favourite, so knowing where the genuine ambiguities are is what makes the
vocabulary safe rather than merely large.

## Value providers

Does the value provider library carry providers for names, streets, cities,
administrative areas and companies in this locale? If not, which ones are
missing? Values and interface text are different problems and only the second is
hand written.

## Anything you can offer

Are you a fluent speaker of this language, and are you willing to review the
vocabulary once it is drafted? A vocabulary written from a dictionary is a
vocabulary that produces confident wrong advice on real pages, which is exactly
the failure this project's first law exists to prevent.
