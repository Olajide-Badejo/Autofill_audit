---
predicts:
  - experiments/results/dev/*p8*
  - experiments/results/test/*p8*
  - experiments/results/analysis/*p8*
  - experiments/results/bench/*p8*
  - src/autofill_audit/audit/thresholds.json
  - models/bert/
---

# Pre-registered: the transformer stretch of spec section 10.7, and the condition that decides it

Author: Olajide Badejo. Date: 2026-08-27. Phase P8, branch `phase/p8-transformer`.

This file is the **first commit of the phase**. It is committed before the
optional training dependencies are installed, before a single weight is
fine-tuned, before any export, and before any number is read off any split. Law
4 requires that a prediction precede the measurement it is about and that the
prediction commit be an ancestor of the result commit;
`scripts/check_prediction_ancestry.py` verifies that mechanically from the front
matter above, at the gate and in CI.

Everything below is either a rule for computing a number or a claim about what a
number will turn out to be. The only observed numbers quoted are prior
measurements from committed result files, and each is cited to the file it came
from.

The point of the file is that it removes the decision from the person who will
be holding the results. By the time the three numbers exist there is nothing left
to decide: the arithmetic below is applied and the answer is read off. Both
answers are a pass of this phase. Spec section 10.7 says so in as many words, and
so does the roadmap entry for P8 in spec section 19: if the transformer does not
ship, the deliverable is the paragraph explaining that it did not, with the
numbers, and that is a successful P8 rather than a failed one.

---

## 1. The ship condition

The transformer ships as a fourth engine if and only if **all three** of the
following hold on the committed test-split run. It is a conjunction. Two out of
three is a no-ship, and so is two out of three by a wide margin on the two.

### Bar A, the unseen locale

The transformer's macro-F1 on the held-out locale slice (`fr-FR`) of the test
split must beat the n-gram model's committed baseline by at least **+0.05
absolute**.

The baseline is 0.5636803327818365, quoted throughout as 0.5637, from
`experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7/metrics.json`,
key `slices.unseen_locale.macro_f1`.

    Bar A: bert_unseen_macro_f1 >= 0.5636803327818365 + 0.05 = 0.6136803327818365

Why this metric and this margin. The held-out locale is the multilingual claim's
only real test (spec section 13.2), it is the slice spec section 10.7 predicts
the transformer's advantage will be concentrated in, and it is the slice where
the n-gram model is weakest and therefore where a win is both most likely and
most useful. The margin is +0.05 rather than +0.01 because the transformer costs
roughly three orders of magnitude more compute per field than the linear model
and adds a tokenizer, a second model format, and a second export path to a tool
whose whole argument is that a fifty-kilobyte linear model is the right default.
A gain that a reader would have to squint at does not buy that. Five points on
the slice the project cares most about does.

### Bar B, no regression overall

The transformer's macro-F1 on the whole test split must not fall more than
**0.01 absolute** below the n-gram model's.

The baseline is 0.7393996960636188, quoted throughout as 0.7394, from
`experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7/metrics.json`,
key `headline.macro_f1`.

    Bar B: bert_macro_f1 >= 0.7393996960636188 - 0.01 = 0.7293996960636188

Why a tolerance rather than a requirement to win. Bar A is the reason to ship and
this bar exists only to stop a model that buys the held-out locale by giving away
the five locales a user is actually on. One point of slack is there because the
two engines abstain differently and macro-F1 is sensitive to rare labels; a
tenth-of-a-point shuffle between two runs is noise and refusing to ship over it
would be superstition. A full point is not noise.

### Bar C, the latency budget

The transformer's p95 CPU latency per field, served through **ONNX Runtime with
dynamic INT8 quantization**, must be at most **5 milliseconds**, that is 5000
microseconds.

    Bar C: bert_p95_latency_us_per_field <= 5000.0

The n-gram engine's committed p95 on the same split is 261.4722470752895
microseconds, from
`experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7/metrics.json`,
key `latency_us_per_field.p95`, so the budget is about nineteen times the
incumbent. Why that is the right shape of budget: a sixty-field form at 5
milliseconds per field is 0.3 seconds of classification, which is still small
beside the page load that dominates the wall clock for every classical engine in
this project, so a transformer inside the budget is a transformer a user would
not feel. A transformer outside it is one that changes what the tool is.

**How Bar C is measured, fixed now so it cannot be chosen later.** The number is
`latency_us_per_field.p95` in the committed test-split `metrics.json`, produced
by the same code path that produced it for every other engine: an onnxruntime
CPU execution provider session created with `intra_op_num_threads = 1` and
`inter_op_num_threads = 1`, one `predict` call per form over that form's
detectable controls, and the elapsed time of that call divided by the form's
field count. It is a per-field share of a batched call rather than a per-call
measurement, exactly as it is for the n-gram engine, and it is compared against
the n-gram engine's figure which was produced the same way. No warm-up pass is
excluded that is not excluded for the other engines, and the session is
constructed once per process before the first form.

### The verdict is mechanical

    SHIP  if  A and B and C
    NO SHIP otherwise

The three numbers are printed side by side with their bars, each bar is marked
met or not met, and the conjunction is evaluated. No number is rounded before
the comparison. Nothing else is consulted, and in particular a comparison that
is statistically significant but fails a bar does not ship, and a bar that is
missed by a hair is missed.

---

## 2. The predictions of spec section 10.7, restated

Spec section 10.7 pre-registers a shape for the result rather than a value, and
it is restated here so that the contradiction is visible if it comes:

> the transformer's advantage, if any, will be concentrated in the **held-out
> locale** and the **hostile** tier, and will be small or negative on the clean
> tier where the n-gram model already has the label text. If the measurement
> contradicts that, the contradiction is the interesting finding and gets
> written up as one.

Written as three separate claims, each of which can be wrong on its own. All
comparisons are against the same committed n-gram run cited above, and every
number in the n-gram column comes out of that file's `grids` block.

**P1. The held-out locale gap narrows.** The transformer's `fr-FR` macro-F1
minus the n-gram model's will be larger than its whole-split macro-F1 difference.
That is the claim that the advantage is *concentrated* in the unseen locale
rather than spread evenly, and it is testable whichever way the differences point.

**P2. The hostile tier gap narrows.** The same statement on the `hostile` tier
of the `tier` grid. The n-gram model's committed hostile macro-F1 is 0.5408632236200269
and its clean is 0.9349757900515733, both from
`experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7/metrics.json`.

**P3. The clean tier does not improve much, and may get worse.** The
transformer's clean-tier macro-F1 will not exceed the n-gram model's by more
than 0.02. The n-gram model reads the label text directly on a clean page and
there is very little headroom above 0.93 for a model that has to compress the
same text through a subword tokenizer and 384 or 768 dimensions.

Three further predictions, added here because a prediction that cannot be wrong
is a description and these can:

**P4. The latency bar is the one that will fail.** This is an estimate, marked
as one. A six-layer, 768-wide encoder over roughly forty subword tokens is on
the order of a hundred times the arithmetic of a sparse dot product against a
7986-column weight matrix, and a single CPU thread is the serving constraint of
spec section 10.5. The estimate is a p95 between 15000 and 60000 microseconds,
that is three to twelve times over Bar C, and the estimate is recorded so that
being wrong about it is visible. If the p95 lands inside the budget, that is a
genuine surprise and gets written up as one.

**P5. The confusion pairs do not change identity.** The four pairs spec section
13.2 predicts (`username` against `email`, `address-level1` against
`address-level2`, `tel` against `tel-national`, `cc-exp` against
`cc-exp-month`) will still be among the transformer's top confusions. A
pretrained encoder does not have information the page does not contain, and
these pairs are ambiguous in the page rather than in the model.

**P6. Calibration will be worse before it is fixed and adequate after.** The
transformer's raw softmax on a fine-tuned classifier over a small corpus is
expected to be more overconfident than the linear model's was, so the expected
calibration error before calibration will exceed 0.02806234539936959, which is
the n-gram model's, from `models/dev_metrics.json`, key
`calibration.before.expected_calibration_error`. After the same one-vs-rest
calibration fitted on dev it is expected to land below 0.10.

---

## 3. The parity contract, stated before the export exists

Spec section 10.5's gate is a parity test and not an export, and the same
discipline applies here. The difference from P4 is that quantization is a
deliberate loss of precision, so demanding exact agreement from it would be
demanding that the quantization not work. The contract is therefore in two
parts and both are pre-stated.

**Part 1, FP32 parity, exact.** Every row of the dev split is run through the
fine-tuned model in PyTorch and through the exported FP32 ONNX graph in
onnxruntime. The gate is **exact argmax agreement on every dev row**, plus a
maximum absolute logit difference at or below **1e-3**. Anything less than exact
argmax agreement means the export is not the model that was trained, and the
recorded response is the same one P4 recorded for its vectorizer: move whatever
diverged out of the graph rather than argue with the converter.

**Part 2, INT8 delta, bounded and recorded.** Dynamic INT8 quantization is
applied to the FP32 graph. Exact argmax agreement against FP32 is **not**
expected and is not required. What is required, and is fixed now:

- the INT8 argmax agrees with the FP32 ONNX argmax on at least **99.0%** of dev
  rows, and
- the INT8 dev macro-F1 is at most **0.01 absolute** below the FP32 ONNX dev
  macro-F1.

Both actual numbers are recorded in the dev metrics result file whichever way
they land. If either bound is broken, the INT8 engine is not the model that was
evaluated, the failure is reported as a failure of the quantized inference path,
and the ship condition fails at Bar C by construction, because Bar C is defined
on the INT8 engine and there is then no INT8 engine to measure.

---

## 4. Training, and what may not be looked at

Identical discipline to P4 and for the same reasons.

- Fitting reads **only** the train partition. Calibration, the threshold
  derivation, and every hyperparameter choice read **only** the dev partition.
  The test partition is not read at all during training, enforced by the same
  `TestPartitionGuard` and its `sys.audit` hook that `scripts/train.py` installs.
- Seed 20260825, propagated to Python, numpy and torch, with the deterministic
  algorithm flags set where the operation has a deterministic implementation.
- Training runs on the GPU. Evaluation and serving run on the CPU execution
  provider with threads pinned to one, like everything else in this project.
- The `excluded` partition is used for nothing, as at P4.
- The hyperparameters that are chosen at all are chosen on dev macro-F1 over a
  grid fixed before the run and recorded in the train manifest with every cell.

**If the GPU cannot be used, that is a result and not a workaround.** The RTX
5070 is a Blackwell part and the installed torch build either supports its
compute capability or does not. That is established by a small CUDA matmul
before any long run and the wheel and CUDA versions are recorded. If no
installable wheel supports it, that fact plus its evidence is a legitimate
no-ship outcome for this phase and is written up as one. What is not acceptable
is a silent multi-hour fallback to CPU training.

---

## 5. Calibration and thresholds, under the P4 policy unchanged

Calibration is fitted on **dev**, one-vs-rest with renormalisation, isotonic
regression above the pre-registered switchover of 100 dev positives per class,
Platt scaling below it, and the identity below 2 positives with the file
recording that the class is uncalibrated. That is the P4 policy in
`scripts/train.py` and it is reused rather than reimplemented.

Thresholds are derived on **dev** by `scripts/derive_thresholds.py` against the
same pre-registered precision target of 0.98 that produced the n-gram block,
under the policy pre-registered in
`experiments/predictions/p4-threshold-derivation.md`. Nothing about that policy
is re-opened here.

**The `bert` block is written into `src/autofill_audit/audit/thresholds.json`
before the test-split run, and it stays there whatever the verdict.** This is
pre-registered because it will otherwise look like a decision made afterwards.
The reason is law 3: the committed test-split result is produced with that block,
and a threshold file that lost the block would make the committed result
unreproducible from the repository. The presence of a block is not a claim that
the engine ships. What decides that is whether `bert` appears in
`EngineChoice`, and the block's `basis` string says which of the two states it is
in. This is the same move P6 made for the `llm` block, pre-registered in the same
way, for the same reason.

---

## 6. The statistical policy for the enlarged family

Unchanged from `experiments/predictions/p5-statistical-policy.md` and
`experiments/predictions/p6-llm-comparison.md`: paired permutation clustered at
the **template**, Benjamini Hochberg across the whole family, alpha 0.05, false
discovery rate 0.05, and a pre-registered practical-effect threshold of **0.02
absolute macro-F1**. The three-way verdict vocabulary is unchanged and the middle
category, significant but below the practical threshold, is reported rather than
promoted.

**The family grows and the size is fixed here, before the runs.** Four engines
give six unordered pairs rather than three, over the same eleven comparisons
each, so the primary family is expected to hold **66** comparisons where P6's
held 33. All six pairs are corrected together in one `adjust_family` call. The
consequence, pre-registered so that it cannot be presented later as a surprise:
every adjusted p value in this phase is larger than the same comparison's
adjusted p value in the P6 analysis, the underlying p values have not moved, and
the P6 analysis file is not touched. Correcting inside a smaller family and
calling it the family is the standard way to manufacture a significant result,
and the size is fixed while fixing it is still free.

**Significance is not part of the ship condition.** Section 1 is the whole of it.
A transformer that wins Bar A significantly and misses Bar C does not ship, and a
transformer that clears all three bars ships whether or not the permutation test
calls the difference significant. Mixing the two would let the phase choose,
after the fact, which of two gates to lean on.

---

## 7. What ships if it ships, and what ships if it does not

**If it ships.** Version 1.1.0 and the tag `v1.1.0`. The model bundle and its
model card land in the same commit (ground rule 8). `bert` joins `EngineChoice`,
the CLI, and the threshold document as a fourth engine. The spec section 13.4
table's `bert-onnx-int8` row stops saying absent and carries the measurement.
The README results section and the report figures are regenerated by their
committed scripts rather than edited.

**If it does not ship.** Version stays 1.0.0 and there is no tag. The deliverable
is the paragraph in `docs/report.md` stating, with the numbers and their result
files, which bars were met and which were not, plus the committed dev and test
result files, the analysis, the decision record, and the log and changelog
entries. The `bert-onnx-int8` row of the spec section 13.4 table stays absent and
its sentence stops saying that the phase has not been built and starts naming the
measured outcome and the result file it is in. `bert` does not join
`EngineChoice` and the shipped tool is unchanged.

That second outcome is not a consolation prize. Spec section 10.7's own sentence
is that a model which is one point better and forty times slower does not ship
and gets a paragraph explaining why, and that this is a more useful contribution
than a slower default. The paragraph is the deliverable, and it is worth more
than a fourth engine nobody should select.

---

## 8. How this file could be violated

Recorded so that a reader can check rather than trust:

1. Changing any of the three bars after seeing any of the three numbers. The
   ancestry check catches the commit; the `amended:` front matter line would have
   to declare it and there is no honest declaration that covers this.
2. Adding a fourth bar, or dropping one, after the fact.
3. Re-running the test split until a run clears a bar. The test split is spent
   the first time it is looked at, `--i-am-measuring` records every look, and
   result files are append-only, so a second run does not replace a first one; it
   sits beside it and both are in the history.
4. Measuring Bar C some other way than section 1 states.
5. Quietly widening the model choice after a first attempt misses, and reporting
   only the second. Every model that is fine-tuned in this phase is recorded in
   the decision record with its outcome, including one that was abandoned.
