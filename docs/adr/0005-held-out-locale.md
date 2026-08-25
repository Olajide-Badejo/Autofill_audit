# ADR 0005: the held-out locale is fr-FR

Date: 2026-08-25
Status: accepted
Phase: P1

## Context

Spec section 8.6 requires one entire locale to be held out of training, as the
*unseen-locale* slice. It is the only honest test of the cross-locale
generalisation claim this project makes, it is the slice on which a transformer
would be expected to beat n-grams at P8, and spec section 5.3 rests its whole
argument for character n-grams on it: character n-grams are the mechanism by
which `postleitzahl` and `postcode` share evidence without a translation table,
and a locale that never appeared in training is the only place that mechanism is
actually under test.

The corpus carries six locales: `en-US`, `en-GB`, `de-DE`, `fr-FR`, `ja-JP`, and
`en-NG`. One of them has to be the held-out one.

The specification also says, in the same section, that the choice is made at P1
and recorded in an ADR, and that it is not to be changed later to make a number
look better. This document exists so that a later change is visibly a change.

## Decision

**`fr-FR` is the held-out locale.** It appears in no training row, whatever
partition its template landed in.

The obvious alternative was `ja-JP`, and rejecting it is the substance of this
decision.

Holding out `ja-JP` would test script coverage rather than generalisation. No
CJK character n-gram would exist in the training distribution at all, so the
model would face a feature space in which essentially every feature was unseen.
A model scoring near zero there would have told us something we already know,
that a bag of character n-grams fitted on Latin text carries no information
about kanji, and it would have told us nothing about whether the model
generalises across languages that share a script. That is a measurement of an
alphabet, not of a method.

`fr-FR` shares the Latin script with four of the other five locales but shares
almost none of the vocabulary: `code postal` against `postal code` against
`PLZ`, `prénom` against `first name` against `Vorname`, `ville` against `city`
against `Ort`. Character n-grams over a shared alphabet are exactly the
mechanism that might carry across that gap, and holding out `fr-FR` isolates the
question the project actually asks: does the model learn what a postal code
field looks like, or does it learn the words that particular locales use for it?

Keeping `ja-JP` in the training partitions has a second benefit that is easy to
miss. Its structural conventions stay learnable: the kana name pair, the postal
code that leads the address block, the prefecture as `address-level1`. Those are
facts about form structure rather than about vocabulary, and they are the part
of Japanese localisation a classifier can genuinely acquire. Holding the locale
out would have discarded that signal along with the script.

## Consequences

- `corpus/split.json` records `held_out_locale`, and every `fr-FR` form is kept
  out of the training partition by `partition_of` in
  `src/autofill_audit/corpus/split.py`, which is the single place that decides
  it.
- A `fr-FR` form whose template landed in train goes to a fourth partition,
  `excluded`, rather than to dev or test. Moving it to dev or test would leak
  the template convention that the split exists to separate, so it is generated,
  recorded, and used by nothing. The reported unseen-locale slice is the `fr-FR`
  forms in dev and test, which are clean on both axes.
- The headline table of spec section 13.4 reports the unseen-locale slice
  separately. A single averaged number over all six locales would hide exactly
  the effect this ADR exists to expose.
- `ja-JP` results are *not* a generalisation claim, and the write-up must not
  present them as one. Japanese is in training; its numbers measure fit, not
  transfer.
- The choice is now load bearing for P4 and P8. Changing it after either has
  produced numbers would be a law-4 violation dressed as an experiment, and
  would require its own ADR superseding this one, with the previous numbers
  retained.

## Alternatives considered

**Hold out `ja-JP`.** Rejected above: it measures script coverage.

**Hold out `en-NG`.** Tempting, because Nigerian address structure differs most
from the others: the postal code is frequently absent, and `address-level1` is a
state. But it shares its vocabulary almost entirely with `en-US` and `en-GB`, so
the lexical half of the transfer problem would be absent and the slice would be
easy for the wrong reason. It would flatter the model.

**Hold out two locales.** Rejected on corpus size. Two held-out locales would
remove a third of the grid from training, and spec section 8.5 already sets a
minimum cell thickness for reporting. One held-out locale is what the corpus can
support without thinning the cells that remain.
