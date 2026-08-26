---
predicts:
  - experiments/results/test/
  - experiments/results/analysis/
---

# Pre-registered: the statistical policy for P5, and what the test split will show

Date: 2026-08-26. Phase P5, branch `phase/p5-eval-triage`.

This file is committed **before** any run against the test split. Law 4 requires
that a prediction about what a measurement will show precede the measurement and
that the prediction commit be an ancestor of the result commit;
`scripts/check_prediction_ancestry.py` verifies that mechanically, using the
front matter above, and it runs at the gate and in CI.

Nothing below is a number observed on the test split. The development-split
numbers that appear in section 5 were committed before this file, in
`experiments/results/dev/`, and each is cited to the file it came from.

---

## 1. The procedure, fixed

Binding for every comparison P5 reports. Changing any of it after a test-split
run has happened is a new prediction file, not an edit to this one.

| Knob | Value |
|---|---|
| Test | Two sided paired permutation between two engines on the identical field set |
| Resampling unit | Sign flips at the **template** level, all fields of a template flipping together |
| Enumeration | Exhaustive when the sign-flip space is at most 50000 vectors, 10000 sampled resamples otherwise |
| Family correction | Benjamini Hochberg across the whole family of comparisons reported in one analysis |
| False discovery rate | 0.05 |
| Alpha | 0.05 |
| Practical effect threshold | An absolute difference of 0.02 in the metric |
| Seed | 20260825, the one seed |

**Why the clustering unit is the template.** Fields inside one template share an
author and are not independent. Resampling them individually would produce
intervals too narrow to believe and therefore claimed significance that is not
there. Spec section 13.3 calls this non-negotiable and it is treated as such.

**Why the practical threshold is absolute, and why it is 0.02.** Below two
points of macro-F1 no user-visible behaviour of the tool changes, because the
thresholds that decide whether a finding is emitted are tuned on a precision
target rather than on raw accuracy, so a classifier two points better produces
the same report on the same page. It is absolute rather than relative because a
relative rule turns one pre-registered threshold into a different threshold in
every slice, and into a very different one in a slice where the baseline is
small.

**Every comparison is reported as one of three outcomes**, plus a fourth that
section 2 explains is unavoidable here: significant and above the threshold;
significant but below the threshold; not significant. The middle one is where
most honest results live and it is the one that must not be quietly promoted
into the first, so the analysis result file carries a count for every category
including the ones with a count of zero.

## 2. The power this design has, computed before the runs

`corpus/split.json` assigns whole templates to partitions, one template per
family to the test split, so the test split holds **five templates**. That is a
fact about the split, committed at P1, and reading it involves no test-split
measurement.

Five clusters give a paired sign-flip space of two to the fifth, which is
thirty-two arrangements. The test is therefore exact rather than sampled, and
the smallest two sided p value it can produce is two over thirty-two, which is
0.0625.

**That is above the pre-registered alpha of 0.05.** So no comparison in the
primary analysis can reach significance, whatever the effect turns out to be.
This is pre-registered rather than discovered afterwards because it is a
property of the design, and a design's power is exactly the thing that must be
known before the data are seen.

Three consequences, all fixed now:

1. Every primary comparison will be reported as inconclusive, in the sense that
   the design cannot reach alpha. That is a different statement from "there is
   no difference" and the write-up must not collapse the two.
2. A p value equal to 0.0625 is not a near miss. It is the floor, and it means
   the observed difference was more extreme than all thirty-one other
   arrangements the clustered design permits. The analysis records that as
   `at_design_floor` so a reader cannot mistake the floor for a marginal result.
3. A **secondary** analysis clustered by form is reported alongside, at a
   hundred and twenty clusters. It is labelled everywhere it appears as
   anticonservative relative to this pre-registered test, because clustering by
   form asserts that two locales of one template are independent, which is a
   stronger assumption than spec section 13.3 makes. It is not the headline and
   nothing in the README will cite it.

Fixing the power problem means generating more templates per family, which
changes the corpus and therefore the model. That is not a P5 change. It is
recorded here and carried into the notes for P6.

## 3. The reporting minimum, and a decision P5 owes

`MIN_FIELDS_PER_REPORTED_CELL` stays at 30. It was fixed at P1, before any
number existed, and moving it now with a grid on screen would mean choosing a
reporting threshold in the knowledge of which cells it suppresses.

P4's handoff asked P5 to decide where the rule applies. The decision, fixed
here, before the test runs: **it applies to the finding-level rates as well as
to the grid cells**, judged separately against each rate's own denominator. A
precision of 1.0 over fifteen accusations and a precision of 1.0 over fifteen
hundred are the same number and are not the same claim, and the first is exactly
what the rule exists to keep out of a table. The counts are reported either way,
so nothing measured is hidden; what is withheld is the invitation to read a rate
off a denominator that cannot support one.

## 4. The engines, and what a finding-level comparison compares

P5 compares `rules` and `ngram` only. The language-model engine arrives at P6
and the transformer does not exist.

Two comparisons are run and they answer different questions.

**Label level.** Macro-F1 and the per-label table on the raw predictions,
threshold free. This is the classifier comparison and it is clean.

**Finding level.** Precision and recall of `MISSING_AUTOCOMPLETE` and
`WRONG_AUTOCOMPLETE` against the answer key, through each engine's own
thresholds. **This is not a comparison of two classifiers.** It is a comparison
of a classifier plus a pre-registered precision target of 0.98 against a rule
table plus a documented tier mapping whose confident band begins at a tier value
that is not a probability at all. Every sentence reporting it must say so. A
table that put the two finding-level recalls side by side without that sentence
would be reporting the answers to two different questions as though they
answered one.

## 5. The predictions

These were fixed before any test-split run. Section 6 records what the
development split already showed, which bears on some of them, and records it
here rather than in a later document so that a reader can see exactly what was
known when the test was run.

**P1. Seen-locale slice, macro-F1.** The n-gram engine beats the rule baseline
by more than the practical threshold of 0.02.

**P2. Unseen-locale slice, macro-F1.** The n-gram engine still beats the rule
baseline, by a smaller margin than on the seen locales, because character
n-grams degrade gracefully across a locale they were not fitted on where a rule
table's vocabulary does not transfer at all.

**P3. Per tier.** The n-gram engine's advantage is largest on the hostile tier
and smallest on the clean tier, because clean markup is what a rule table is
best at and hostile markup is where a learned model's redundancy should pay.

**P4. The four confusion pairs**, restated for the test split from spec section
13.2 and from P4's prediction file. Each of these pairs appears among the
confusions of at least one engine on the test split, in at least one direction:
`username` against `email`, `address-level1` against `address-level2`, `tel`
against `tel-national`, `cc-exp` against `cc-exp-month`.

**P5. Abstention.** The n-gram engine abstains less often than the rule
baseline, and is more accurate than the rule baseline on the fields it does
commit to.

**P6. Latency.** Both engines stay below one millisecond per field at the
ninety-ninth percentile, and the n-gram engine is the slower of the two, because
its featurisation enumerates n-grams in Python where the rule table matches a
handful of regular expressions.

**P7. The wall-time split.** Loading and extracting the page dominates the whole
run, so classifier latency differences, whatever they are, are irrelevant to
what a user waits for.

## 6. What the development split already showed, recorded before the test run

The development-split sanity runs were taken and committed before this file. The
order matters: it means these numbers were available when the predictions above
were carried into the test split unchanged, and hiding that would be worse than
reporting it.

From `experiments/results/dev/2026-08-26T02-47-47Z_rules_85d7445/metrics.json`
and `experiments/results/dev/2026-08-26T02-47-47Z_ngram_85d7445/metrics.json`:

| Metric, development split | rules | ngram |
|---|---|---|
| macro-F1 | 0.7716 | 0.5813 |
| macro-F1, seen locales | 0.7803 | 0.6077 |
| macro-F1, unseen locale | 0.6938 | 0.4306 |
| macro-F1, clean tier | 0.8727 | 0.7404 |
| macro-F1, hostile tier | 0.4175 | 0.4046 |
| abstention rate | 0.2737 | 0.0546 |

**Predictions P1, P2 and P3 are already contradicted on the development split.**
The rule baseline wins macro-F1 everywhere, by far more than the practical
threshold, and the n-gram engine's deficit is smallest on the hostile tier
rather than largest. Prediction P5's first half holds on development and its
second half does not.

They are carried into the test split unchanged anyway, and that is the honest
thing to do rather than the lazy one. The predictions were fixed as a statement
about what the model was expected to do; rewriting them now to match what the
development split showed would produce a document that predicts the past. What
this section buys is that a reader of the eventual report can see the prediction
and the contradicting development evidence in the same commit, dated before the
measurement, rather than discovering afterwards that the prediction was already
in doubt.

The test split can still differ. It is five different templates, and the model's
calibration and both of its thresholds were fitted on development, so
development is if anything the split where the n-gram engine should look best.

## 7. What is measured, and where it lands

Two test-split runs, one per engine, each with `--i-am-measuring`, writing to
`experiments/results/test/<run id>/` as a run log at the spec section 13.1
schema, a manifest at spec section 18, a metrics document, a confusion matrix,
and the per-field finding-level judgements.

One analysis, writing to `experiments/results/analysis/<run id>/`, carrying the
primary and secondary families, the Benjamini Hochberg adjusted p values, the
three way classification with a count for every category, and what the external
harness's own parser made of an unmodified run log.

Both test-split runs extract through a real browser rather than from the
descriptor cache, so that the load and extract columns of the wall-time split
are real measurements on both engines rather than a cache read on the second.
