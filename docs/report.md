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
