---
predicts:
  - src/autofill_audit/audit/thresholds.json
amended: 2026-08-26 at P5, front matter added so the ancestry check can read the mapping. No prediction text changed. The amending commit is later than the threshold commit, which is exactly why this line is required rather than optional.
---

# Pre-registered: how P4 derives the two decision thresholds

Date: 2026-08-26. Phase P4, branch `phase/p4-ngram-onnx`.

This file is committed **before** any threshold is computed, before the model is
trained, and before any dev-split number is looked at. Law 4 requires that a
prediction about what a measurement will show precede the measurement, and that
the prediction commit be an ancestor of the result commit. The ancestry check at
P5 (`scripts/check_prediction_ancestry.py`) verifies that mechanically, so this
file is worth nothing if it is amended after the numbers arrive. It will not be.

Everything below is a rule for computing a number, or a claim about what the
number will turn out to be. Nothing below is a number that has been observed.

---

## 1. The optimisation that fixes the two thresholds

Spec section 11.3 says the two thresholds are chosen on the dev split by a
stated optimisation against a pre-registered precision target, never tuned on
test, and never typed by hand. Here is the statement.

### 1.1 The target

```
target_precision = 0.98
```

Fixed now, before looking. The reasoning, which is the part that matters more
than the value: at or above `tau_high` the tool tells somebody to edit
production markup. A false `CRITICAL` costs a developer an argument with their
own codebase and costs this project the credibility that makes the next finding
worth reading; a missed one costs a field that would not have autofilled anyway.
Those two are not symmetric and the target is set where the asymmetry says to set
it. A target of one would be dishonest rather than strict, because a finite dev
split cannot demonstrate a precision of one, and rounding a sample estimate up to
certainty is exactly the move law 4 exists to forbid.

### 1.2 tau_high

**`tau_high` is the smallest calibrated confidence at which dev-split precision
for `MISSING_AUTOCOMPLETE`-eligible predictions reaches the target.**

Eligible means: the audit engine's primary chain, run on that dev field, would
reach the `MISSING_AUTOCOMPLETE` branch if the confidence were high enough. That
is the same set of conditions `audit/engine.py::_primary` already applies, so
eligibility is read off the decision procedure rather than invented beside it:

- the descriptor is not an undetectable blind spot;
- the page declares no `autocomplete` on it, and no `autocomplete="off"`;
- the inferred label is not `UNKNOWN`, not `NOT_AUTOFILLABLE`, and not
  `COMPOSITE_UNSPLIT`;
- the inferred label has a declaration a correct page would carry.

A prediction is **correct** when the token the tool would tell the developer to
add is the token the answer key says the field should carry, or is equivalent to
it under the documented equivalence sets of `audit/findings.py`. Equivalence is
used because a page that declares `name` where this tool reads `given-name` fills
correctly from a stored profile, and calling that a false accusation would
measure something other than what a user experiences.

Precision at a threshold is (correct accusations) / (all accusations at that
threshold). If no threshold in the unit interval reaches the target, `tau_high`
is set to the smallest threshold that maximises precision, and the shortfall is
recorded in `thresholds.json` and in the model card rather than hidden by
lowering the target after the fact.

### 1.3 tau_low

**`tau_low` is the greatest confidence at which the band `[tau_low, tau_high)`
still captures at least half of the recall that `tau_high` gives up.**

```
recall_band_fraction = 0.50
```

The task file words this as "the smallest confidence such that the band captures
at least 50 percent". Captured recall is monotonically non-increasing in
`tau_low`, so every value below a qualifying one also qualifies and the smallest
qualifying value is always zero, which is a threshold that says nothing. The
non-degenerate reading, and the one used here, is the greatest qualifying value:
the narrowest band that still meets the capture target, which is the band with
the best precision among those that meet it. This resolution is written down here,
before the computation, rather than chosen afterwards from two answers.

Concretely, with `R_all` the recall the tool would reach if every eligible
prediction were acted on regardless of confidence, and `R_high` the recall at
`tau_high`:

- recall given up is `R_all - R_high`;
- the band captures the correct eligible predictions whose confidence lies in
  `[tau_low, tau_high)`;
- `tau_low` is the greatest value for which captured recall is at least
  `recall_band_fraction * (R_all - R_high)`.

If `tau_high` gives up no recall at all, the band has nothing to capture and
`tau_low` is set equal to `tau_high`, which empties the near-miss band honestly
rather than putting an arbitrary number there.

### 1.4 Candidate thresholds

Candidates are the observed calibrated confidences on the eligible dev subset,
plus zero and one. Choosing from the observed values rather than from a fixed
grid means the chosen threshold is always achievable and never falls in a gap
that no dev field occupies.

### 1.5 What the file records

`src/autofill_audit/audit/thresholds.json` will carry, when the derivation runs:
the two values, the target that drove them, the achieved dev precision and
recall, the corpus manifest sha, the date, and a `basis` string naming the dev
split rather than the rule-tier mapping it replaces.

---

## 2. The other decisions fixed before measurement

Recorded here so that none of them can be quietly retuned once a number is
visible.

### 2.1 Calibration

One-vs-rest with a renormalisation step, fitted on dev and never on train or
test (spec section 10.4). The switchover:

```
isotonic regression   for a class with at least 100 dev examples
Platt scaling         for a class with fewer
```

The per-class method actually used is recorded in `calibration.json` so that the
model card states what happened rather than what was intended. The expectation,
recorded as a prediction: **most classes will fall below the isotonic
switchover** and will be calibrated with Platt scaling, because the dev split is
one fifth of a corpus spread over forty two labels and the arithmetic does not
leave room for many classes above the threshold. If that turns out false it will
be because the corpus is more concentrated than expected, which is itself worth
recording.

### 2.2 Features

Fixed now, not tuned against test (spec section 10.2):

```
char_wb n-grams, 3 to 5,  min_df 2,  at most 100000 features
word n-grams,   1 to 2,   min_df 2,  at most  50000 features
```

Plus the categorical one-hots, option-shape features, and structural features of
spec section 10.2 blocks 3 to 5. The vocabulary is fitted on train only and is
committed with the model. Hashing is the recorded fallback and would cost
per-feature evidence, which the model card would then have to state.

### 2.3 The sweep

L2 multinomial logistic regression, `class_weight="balanced"`, chosen on dev
macro-F1 over:

```
C in {0.25, 0.5, 1.0, 2.0, 4.0, 8.0}
```

The grid and every cell's dev macro-F1 go into `dev_metrics.json`.

---

## 3. Advance predictions about what the measurement will show

These are predictions, not results. Each is written so that it can be wrong.

### 3.1 The confusion pairs

Spec section 13.2 names four pairs it expects to dominate the confusion matrix.
They are predicted in advance here, under law 4:

- `username` against `email`, in both directions. A login form's username field
  frequently accepts an email address and is often labeled as one, so the two
  share their whole vocabulary on exactly the forms where they differ.
- `address-level1` against `address-level2`. State, province, county, city, and
  town are one lexical field split by a convention that varies per country, and
  the corpus spans six locales that do not agree about it.
- `tel` against `tel-national`. The two differ by whether a dialling code is
  expected, which is a fact about the form's intent and is almost never in the
  markup.
- `cc-exp` against `cc-exp-month`. A single MM/YY control and the month half of
  a split pair carry nearly identical labels and identifiers, and the structural
  difference between them lives in `group_role` rather than in any text.

Predicted additionally, beyond the four the specification names:
`address-line1` against `street-address`, for the same reason as the address
levels, and `CC_EXP_SPLIT_MONTH` against `cc-exp-month`, which differ only by
whether group detection fired.

### 3.2 Where the model will be weakest

- **The held-out locale.** `fr-FR` appears in no training row (spec section 8.6),
  so its character n-grams are unseen and its word forms are entirely unseen.
  Macro-F1 on the `fr-FR` dev forms is predicted to be materially below macro-F1
  on the seen locales. Character n-grams are predicted to carry more of that
  slice than word n-grams do, because French and English share Latin substrings
  (`postal`, `adresse` against `address`, `national`) where they share few whole
  tokens.
- **The hostile tier.** Labels are stripped, identifiers are obfuscated, and the
  only evidence left is placeholder text, option lists, and structure. Predicted
  to be the weakest tier, and predicted to be the tier where the calibrated
  confidences sit lowest, which is the behaviour that keeps the tool quiet rather
  than wrong.
- **Rare labels.** `honorific-suffix`, `one-time-code`, `tel-extension`, and
  `address-line3` will have few training rows each. `class_weight="balanced"` is
  in the design for exactly this, and macro-F1 is the headline metric because it
  is the one that punishes ignoring them. Predicted: recall on these will be the
  worst per-class numbers in the table, and at least one of them will be
  predicted correctly almost never.

### 3.3 Calibration

Predicted: the uncalibrated model will be **overconfident**, which is the
documented behaviour of a regularised linear model on a small corpus (spec
section 10.4), and expected calibration error will fall after calibration.
Predicted also: calibration will lower the top-class probabilities enough that
fewer dev fields clear any given threshold, so the derived `tau_high` will sit
below the rule engine's current confident-band boundary while accusing on fewer
fields than the raw model would have.

### 3.4 The comparison the README is not allowed to make yet

No number from this phase goes into the README (law 3). The n-gram engine's
measured comparison against the rule baseline is a P5 result with a run manifest
behind it, and P4's dev numbers are development artefacts that inform the
thresholds and nothing else.

---

## 4. What would falsify the design rather than the model

Worth naming, so that a bad outcome is recognised as one rather than absorbed.

- **If no confidence reaches the precision target on dev**, the honest response
  is to record the shortfall, keep the threshold at the best achievable
  precision, and say plainly in the model card that the tool cannot reach its own
  target on synthetic dev data. It is not to lower the target.
- **If expected calibration error stays poor after calibration**, spec section
  10.4 names the response: raise the abstention threshold and report more
  `UNKNOWN`. Not ship confident wrong numbers.
- **If ONNX and scikit-learn disagree on any dev row**, the parity gate fails and
  the spec section 10.5 fallback is taken, which is recorded in ADR 0006 either
  way.
