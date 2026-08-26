---
predicts:
  - src/autofill_audit/audit/thresholds.json
  - models/
  - docs/model-card.md
  - experiments/results/test/*p5r*
  - experiments/results/analysis/*p5r*
---

# Pre-registered: the corpus power repair, and what the re-measurement will show

Date: 2026-08-26. Phase P5R, branch `phase/p5r-power-repair`.

This file is committed **before** the template work, before the regeneration,
before the retraining, and before any run against the new test split. It is the
first commit of the phase, together with the engineering-log entry that explains
in advance why every recorded metric in this repository is about to move and the
changelog entry that records it.

`scripts/check_prediction_ancestry.py` verifies the front matter above
mechanically: the commit that adds this file must be an ancestor of the commit
that last touches each path it names.

## 0. Why the front matter names a pattern rather than a directory

P5's policy file names `experiments/results/test/` and
`experiments/results/analysis/` in full, and it can, because it was committed
before anything existed under either. This file cannot make the same claim: those
directories already hold P5's runs, which were measured before this prediction
was written and which this phase does not touch, edit, or delete. Naming the
whole directory would assert that this prediction preceded results it did not
precede, which is the exact failure law 4 exists to catch, and the ancestry check
would correctly refuse it.

So the front matter names the two patterns `*p5r*`, and every run this phase
takes carries `p5r` in its run id. The claim is therefore precisely the true one:
this prediction precedes the runs of this phase and says nothing about the runs
of the last one.

## 1. The defect being repaired, restated

Spec section 13.3 requires the resampling unit to be the template, because fields
inside a template share an author. P1's leakage rule assigns whole templates to
partitions and the realised grid carried five templates per family at a 3/1/1
split, so the test partition held **five templates**. A paired sign-flip
permutation over five clusters has two to the fifth, thirty-two, arrangements,
and the smallest two sided p value such a design can produce is two over
thirty-two, which is 0.0625.

The pre-registered alpha is 0.05. All eleven of P5's comparisons therefore came
back `inconclusive: the design cannot reach alpha`, seven of them sitting exactly
at that floor. That is a property of the design and not of the engines, and no
number of resamples fixes it.

| Test templates | Arrangements | Smallest attainable two sided p |
|---|---|---|
| 5 | 32 | 0.0625 |
| 6 | 64 | 0.0313 |
| 8 | 256 | 0.0078 |
| 10 | 1024 | 0.0020 |

Six test templates is the minimum that clears alpha at all and it clears it by
one arrangement. Ten is the number this phase builds.

## 2. The repair, fixed before anything is generated

Binding. Changing any of it after a run has happened is a new prediction file
rather than an edit to this one.

| Knob | Before | After |
|---|---|---|
| Templates per family | 5 | 8 |
| Templates in total | 25 | 40 |
| Split per family, train/dev/test | 3/1/1 | 5/1/2 |
| Test templates | 5 | 10 |
| Sign-flip arrangements on test | 32 | 1024 |
| Smallest attainable two sided p | 0.0625 | 0.0020 |
| Forms in total | 600 | 960 |
| Seed | 20260825 | 20260825, unchanged |
| Held-out locale | fr-FR | fr-FR, unchanged |
| Target precision behind tau_high | 0.98 | 0.98, unchanged |
| Practical effect threshold | 0.02 absolute | 0.02 absolute, unchanged |
| Alpha, false discovery rate | 0.05 | 0.05, unchanged |
| Reporting minimum per cell | 30 fields | 30 fields, unchanged |

**Nothing in the statistical policy moves.** The whole point of repairing the
corpus rather than relaxing the level is that the level stays where P5 fixed it,
so this phase's verdicts are comparable with the ones P5 could not reach. A
change to the target precision, the alpha, or the practical threshold at the same
time as a change to the corpus would make the two moves impossible to attribute,
and the second of them would look exactly like moving a goalpost.

**The label coverage rule is new and is the one addition.** Every taxonomy label
a model can predict must appear in the **train** partition with at least twenty
rows. Twenty is not a taste: one training template contributes exactly twenty
rows for a field it carries in every locale, because a template is generated in
six locales and the held-out locale is lifted out of train. So the constant says
"at least one whole training template carries this label", which is the smallest
statement that is not an accident of a single locale profile. Three labels sit at
zero train rows in the current corpus, `country-name`, `one-time-code` and
`street-address`, and the three new templates per family are designed to carry
them deliberately rather than to acquire them by luck. `UNKNOWN` stays reachable
only through the generator's undeterminable control and stays documented as
rule-unreachable in `docs/taxonomy.md`.

## 3. What this invalidates, stated before it is done

Every one of these is expected, is a consequence of the repair, and is not a
regression to be explained away afterwards:

- the corpus manifest sha, and therefore the descriptor cache bound to it;
- the model, its vocabulary, its calibration and its evidence table, because the
  training set is now twenty-five templates rather than fifteen;
- both decision thresholds, which are derived on a dev split that is now a
  different five templates;
- every metric in `models/dev_metrics.json` and in the model card;
- every number in the README, which will cite the new runs.

The old result files are not touched. They are the first, underpowered
measurement, they were correctly taken, and spec section 18 makes them
append-only history. Documents may refer to them as what they are.

## 4. The predictions

Fixed here, before the templates are written.

**P1. The ordering persists.** The rule baseline still beats the n-gram engine on
macro-F1 on the test split, overall and on the unseen-locale slice. The mechanism
P5 identified is abstention asymmetry: the rule table answers `UNKNOWN` on about a
quarter of the fields and is right on almost everything it does answer, while the
model answers nearly everything and pays twice for each wrong rare-class guess
under macro averaging. More templates give the model more data, but they do not
change either engine's policy about when to speak, so the ordering should
survive.

**P2. The n-gram engine improves in absolute terms.** Its test-split macro-F1 is
higher than the 0.4151 it scored on the old design
([metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json)),
because the training partition grows from fifteen templates to twenty-five, and
because no label it can predict is trained on zero rows any more. P5's model had
three labels with no training rows at all and twelve classes with no dev
positives, and a class the model has never seen is a class it can only get wrong.

**P3. The primary comparisons clear the design floor.** With ten test clusters
the smallest attainable two sided p is 0.0020, well below the alpha of 0.05, so
no comparison is reported as `inconclusive: the design cannot reach alpha` for
design reasons. Every comparison therefore lands in one of the three categories
spec section 13.3 requires: significant and above the practical threshold,
significant but below it, or not significant. **This prediction is about
certifiability rather than about direction**, and it is satisfied whichever way
the verdicts fall, including the case where the difference this project expects
to be large turns out not to be certifiable at ten clusters either. That outcome
would be a real finding rather than a failure, and it would be reported as one.

**P4. Page load still dominates the wall time.** The share of wall time spent
loading and extracting the page stays above nine tenths for both engines, so
neither engine's classifier latency is what a user waits for. This held at P5 for
both engines and the mechanism, a browser being slower than a regular expression
or a small matrix multiply, does not change with more templates.

**P5. Latency stays inside a millisecond per field at the ninety-ninth
percentile** for both engines, and the n-gram engine stays the slower of the two.
Its featurisation enumerates n-grams in Python. A wider training vocabulary makes
that slower rather than faster, so the gap should widen slightly.

**P6. The finding-level precision of both engines stays at or very near one.**
Both engines accused only fields that needed accusing on the old design. The
threshold policy that produced that is unchanged, so a large drop in precision
would mean the threshold derivation had picked up something about the new dev
split rather than about the model.

## 5. What is measured, and where it lands

Two runs against the new test split, one per engine, each with
`--i-am-measuring`, each extracting through a real browser rather than from the
descriptor cache, writing to `experiments/results/test/<run id>/` with `p5r` in
the run id. One analysis over the pair, writing to
`experiments/results/analysis/<run id>/` with `p5r` in the run id, carrying the
primary family clustered by template, the secondary family clustered by form
labelled anticonservative as before, the Benjamini Hochberg adjusted p values,
and a count for every outcome category including the ones with a count of zero.

The dev split is read for calibration and for the threshold derivation, as at P4,
and for nothing else. The test partition guard stays armed throughout training and
threshold derivation.
