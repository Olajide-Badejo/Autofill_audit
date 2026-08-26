# Report

The full write-up is a P7 deliverable: method, corpus, headline experiment,
results by reference, limitations, and what would be measured next. The LaTeX
long form lives in `report/`.

This file exists now because one policy had to be fixed before any number was
produced, and fixing it afterwards would mean choosing a reporting threshold
with knowledge of which cells it would suppress.

## Reporting policy

### The insufficient-data rule

**A locale by tier cell is reported as a percentage only when it holds at least
30 fields. Below that it is reported as "insufficient data".**
<!-- traceability: policy constant fixed at P1, not a measurement; the code is MIN_FIELDS_PER_REPORTED_CELL -->

Spec section 8.5 states the reason plainly. A three-field cell showing
`100% accuracy` is a lie that formats correctly: a reader scanning a grid sees
a number and reads it as a measurement, and nothing in the rendering tells them
the denominator was too small for it to mean anything.

The threshold is a decision rather than a judgement call, and it is enforced by
code rather than by whoever is writing the table:

- The constant is `MIN_FIELDS_PER_REPORTED_CELL` in
  [`src/autofill_audit/evaluate/metrics.py`](../src/autofill_audit/evaluate/metrics.py),
  with `is_reportable()` beside it.
- P5's metrics code imports it. There is no second copy and no per-table
  override.
- A suppressed cell renders the string "insufficient data", not a blank. A blank
  cell reads as an oversight; this one is a decision, and it should look like
  one.

The value was chosen at P1, before any corpus had been generated and before any
accuracy had been computed, which is the only point at which it could be chosen
without knowledge of its effect.

### Numbers in this repository

Law 3 governs everything below this line, once there is anything below it. No
number appears in the README, in `docs/`, in any report, or in any plot unless
it is reproducible from a committed file under `experiments/results/` whose
manifest sha resolves to a real commit in this repository. Hand-typed numbers
are forbidden.

`scripts/check_traceability.py` enforces this mechanically in CI. Two things
clear a line that would otherwise be a violation: a result-file reference on the
same line, or an explicit `traceability` annotation for a number that is
configuration rather than measurement. The threshold above carries such an
annotation, and that is the correct use of it. A measurement must never carry
one.

### The realised corpus grid

Not recorded here. The generator writes it to `corpus/manifest.json` with
per-cell counts, per-form sha256, and the split assignment sha, and spec section
8.5 asks for it to live there rather than in prose. Two corpora with the same
manifest sha are the same corpus.

## The headline experiment, answered

Draft. The full write-up is P7; this section exists because spec section 19's P6
gate requires the question of spec section 13.4 to be answered with numbers,
whichever way it went, at the phase that produces them rather than at the phase
that typesets them.

### The question

<!-- traceability: a quotation of the build specification's own question, not a measurement -->
> Does a 50-kilobyte linear model that runs in microseconds on a CPU get close
> enough to a 12-billion-parameter model to be the right default for a developer
> tool?

### The answer

**Yes, and the question understates it. The linear model did not have to get
close, because it won.**

The test split, three engines ([manifest.json](../experiments/results/bench/2026-08-26T20-32-48Z_bench_6457ac7/manifest.json)).
Macro-F1 and micro-F1 are both reported because they disagree about which of the
two classical engines leads, and a table carrying one of them would be picking a
winner by picking a denominator.

| Engine | macro-F1 | micro-F1 | unseen locale | abstention | p95 latency | cost | Result file |
|---|---|---|---|---|---|---|---|
| `rules` | 0.7911 | 0.7678 | 0.7276 | 0.2620 | 134.0 | null | [metrics.json](../experiments/results/test/2026-08-26T21-15-35Z_p6-rules_6457ac7/metrics.json) |
| `ngram` | 0.7394 | 0.8226 | 0.5637 | 0.0363 | 261.5 | null | [metrics.json](../experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7/metrics.json) |
| `llm` | 0.6353 | 0.6953 | 0.6045 | 0.0255 | 674727.4 | null | [metrics.json](../experiments/results/test/2026-08-26T20-32-48Z_p6-llm_6457ac7/metrics.json) |
| `bert-onnx-int8` | absent | absent | absent | absent | absent | absent | not built, phase P8 |

Latency is microseconds per field. The fourth row is absent rather than blank
because it is phase P8 and has not been built, and a blank cell reads as a
measurement of zero.

The language model is `mistral-nemo:12b-instruct-2407-q4_K_M` on a local GPU
through Ollama, structured output enforced by the server, temperature 0, seed
recorded, determinism not claimed. Its latency figure is a batch's elapsed time
divided by that batch's field count rather than a per-field measurement, because
it classifies a page in one request.

### What that answer does and does not license

**Licensed.** On this corpus, the n-gram model is the better classifier as well
as the better product. The recommendation that the tool should default to it does
not rest on a latency argument at all; it rests on accuracy, and the latency and
footprint arguments are additional rather than load bearing.

**Not licensed.** Any claim that language models are bad at this task. What was
measured is one 12B model at 4-bit, with one prompt, on a synthetic corpus, where
the entire input is a short list of attribute strings. That is close to the worst
case for a system whose advantage is world knowledge and close to the best case
for one that memorises naming conventions, and the two classical engines were
fitted on this corpus's own training split while the language model saw it for
the first time. A fine-tuned model, a better prompt, or real pages could each
move this, and none was tried.

### The one place the language model led

Its `MISSING_AUTOCOMPLETE` recall is the highest of the three and the difference
is certified after correction
([analysis.json](../experiments/results/analysis/2026-08-26T21-20-11Z_p6-analysis_6457ac7/analysis.json)).
It found more of the real defects than either classical engine. It also had the
worst precision on both accusation codes, by margins the same test certifies.

That trade is not a property of the model. It is a property of its threshold
block, which is zero and zero because spec section 12.1 forbids a self-reported
confidence from gating anything, and which was registered before the run. The
language model accuses whenever it has an answer; the other two accuse only above
a boundary. **A finding-level comparison between them is a comparison of three
policies, not three classifiers**, and that sentence has to travel with the table.

### What the answer cost

The language-model run took about forty-three minutes of wall clock against about
two and a quarter minutes for each classical engine, over the identical page set ([llm](../experiments/results/test/2026-08-26T20-32-48Z_p6-llm_6457ac7/metrics.json), [rules](../experiments/results/test/2026-08-26T21-15-35Z_p6-rules_6457ac7/metrics.json)).
For the classical engines the browser is essentially the whole runtime; for the
language model it is a twentieth of it. That inversion is the product finding,
and it is more robust than the accuracy gap because it does not depend on the
corpus being synthetic.
