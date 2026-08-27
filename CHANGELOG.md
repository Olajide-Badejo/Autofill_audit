# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-08-27

The documentation release. No behaviour changes: the classifiers, the audit
engine, the thresholds and the renderers are byte-identical in behaviour to
`0.4.0`, and the only change to shipped output is the version string.

What lands is the evidence layer that makes the previous six phases readable by
somebody who was not there. Three compiled reports, the full documentation set,
all seven architecture decision records, a demo and a sample report generated
from a committed fixture, and the table and figure generators that make law 3
mechanical for a typeset document rather than a matter of care.

**The `v1.0.0` git tag is deliberately not applied.** Spec section 0.5 forbids
tagging a stable release while any dependency is a git ref rather than a
released version, `ml-experiment-triage` is still unpublished, and that rule was
written on the first day of this project and holds now that it is inconvenient.
The version is bumped here and in code; the tag waits on
[the publication task](docs/cross-repo-tasks.md). Vendoring the three functions
this project uses would remove the blocker and would delete the evidence the
boundary exists to produce, which is why it is refused rather than merely not
done.

### Added

- **`report/main.pdf` and its source.** The public write-up of spec section
  17.2: the problem, the taxonomy and its provenance, the corpus design and the
  split, the extractor and its blind spots, the classifier ladder, the audit
  engine's decision procedure and threshold policy, the headline experiment in
  full with per-locale and per-tier grids and the confusion tables, the
  statistical procedure with every comparison in the corrected family, the
  pre-registered predictions beside their outcomes, the limitations and the
  future work. Chapters under `report/chapters/`, bibliography in
  `report/refs.bib`.
- **`report_debug/debug_report.pdf` and its source.** The record of what went
  wrong, of spec section 17.3, grouped by theme rather than by date: DOM
  traversal and shadow boundaries, waiting and flake, normalisation and the rule
  vocabulary, generator determinism, export fidelity, thresholds and
  reliability, language model schema behaviour and serving, the package
  boundary, the corpus power repair, the enforcement checks themselves, and a
  final chapter of what is still open. Each entry states the symptom, the
  diagnosis, the fix, and what was considered and refused.
- **`scripts/make_report_tables.py` and `scripts/make_report_figures.py`.** Every
  table and every figure in the reports is generated from a committed file under
  `experiments/results/` or `models/`. Two conventions make the output survive
  the CI checks that scan LaTeX sources: every emitted line carrying a digit ends
  in a comment naming the file its digits came from, and no two adjacent hyphens
  are ever written. The generators also emit `report/tables/values.tex`, one
  macro per number the prose quotes, so **the chapters of all three reports
  contain no digits at all**.
- **`docs/adr/0002-taxonomy-is-the-autocomplete-spec.md`**,
  **`docs/adr/0003-classifier-ladder-order.md`** and
  **`docs/adr/0004-triage-stays-external.md`**. Written now, from the recorded
  evidence, for decisions taken at P1, P3 and P5. An ADR is supposed to be
  written when the decision is made; the lateness is recorded in each file
  rather than hidden, and each names the artefacts it was reconstructed from.
  All seven records are now present and dated.
- **`docs/assets/demo.gif`** and `scripts/make_demo_gif.sh`. The animation is a
  real run against `tests/fixtures/checkout_hostile.html`: the script captures
  the tool's own stdout and exit status and renders them as frames. Frames
  rather than a terminal recorder, because a recorder captures wall clock
  timings and a committed asset that cannot be reproduced byte for byte is a
  committed asset nobody can check.
- **`docs/examples/checkout_hostile_report.html`.** The HTML renderer's output
  on the same fixture, committed so a reader can see what the tool produces
  without installing it.
- **`CONTRIBUTING.md`**, covering the phase-gate discipline, the four laws, the
  dash rule and its LaTeX collision, and the synthetic-data-only rule.
- **Issue templates** under `.github/ISSUE_TEMPLATE/`: bug, false positive,
  false negative, new locale. The false-positive template is the important one,
  because it is the feedback channel that improves the thing the tool is judged
  on.
- **`make tables`, `make reports` and `make reports-clean`.** `make reports`
  regenerates the tables and figures from result files and then builds every
  report present, with `latexmk -auxdir=build` so that intermediates land in
  each report's gitignored `build/` directory and the compiled PDF sits beside
  its source where it is committed. `make reports-clean` removes everything the
  target produces, so `make reports-clean reports` is a build from nothing.

### Changed

- **Version bumped to `1.0.0`.** The golden snapshots are refreshed for it and
  the diff is the version string and nothing else, across nine files, which is
  the evidence that no behaviour moved.
- **`README.md` rewritten around the reports.** The demo is above the fold, the
  three write-ups are linked in a table near the top under the heading a reader
  actually asks, the worked before-and-after is one attribute on one input, and
  a mermaid diagram of the real pipeline names the modules and marks
  `FieldDescriptor` as the load-bearing contract between the extractor and the
  classifiers. The status section is corrected: `--engine auto` is the default
  and the measurements recommend the n-gram model, which the previous text
  predated.
- **`docs/report.md` completed.** It was a policy note and a draft answer; it is
  now the full markdown write-up of spec section 17: method, corpus, the three
  engines and the three decisions that decide whether the comparison measures
  anything, the reporting policy, the results, the limitations including the
  double-classification note, and what would be measured next.
- **`docs/cross-repo-tasks.md`** carries a P7 status review of all five issues
  and the publication task, each checked rather than assumed. Nothing has
  closed. The section also records the *Used by* cross-link now present on the
  other repository's README.
- **`docs/environment.md`** records the exact LaTeX packages the three documents
  use, which ADR 0001 promised P7 would supply so that a machine without a full
  TeX installation can reach the same result; how `make reports` is wired and
  why the auxiliary directory is separated from the deliverable; the demo
  animation's mechanism; and the Ollama serving route as resolved at P6.
- **`docs/references.md`** re-verified from the build machine on the release
  date. Every entry answered the same status as at P0 and none had moved. The
  bibliography in `report/refs.bib` is assembled from this file and from nothing
  else.
- **`docs/model-card.md`** now opens with the fact that the training manifest of
  the shipped model is marked dirty, why, exactly what follows from it, and why
  it is recorded rather than repaired. The dev-split numbers in the card sit one
  notch below the test-split numbers on this project's own scale, and a reader
  is entitled to know that without going and finding it.
- `requirements.lock` regenerated to add `matplotlib` and its transitive
  packages to the `dev` extra, for the report figures. It is a development
  dependency for the same reason the evaluation harness is one: the audit path
  never imports it, and a `pipx` install of a command line auditor has no
  business carrying a plotting stack. `Pillow` arrives with it and is what
  renders the demo animation.
- The `check-added-large-files` pre-commit hook now excludes `report/` and
  `report_debug/`. The compiled PDFs are deliverables rather than build output,
  their sources and generated inputs are all committed so the PDF is
  reproducible rather than opaque, and requiring a multi-gigabyte typesetting
  installation to read a report is a worse trade than half a megabyte in the
  repository.

### Known limitations, stated in the release rather than discovered after it

- **The evaluation runner classifies every form twice**, once directly and once
  through the audit engine, so a row's `pred_label` and its `finding_codes` come
  from two different draws for a non-deterministic engine. Measured on the
  headline run against the deterministic rule engine as a control, the excess
  disagreement is on the order of two fields in seven hundred. It is not fixed
  here, because changing what the runner does for every engine after seeing the
  results is the regeneration spec section 18 forbids. The fix is to pass the
  first pass's predictions into the audit rather than letting the audit
  re-classify.
- **The shipped wheel cannot compute its own significance tests**, because the
  evaluation harness sits in the `dev` extra.
- **A published wheel carries no model**, so an install runs the rule baseline
  until the user trains one or points `AUTOFILL_AUDIT_MODEL_DIR` at a bundle.
  Documented behaviour rather than a silent fallback, and on the future-work
  list.
- **Real-world accuracy is unmeasured** and is stated as unmeasured everywhere a
  number appears.

## [0.4.0] - 2026-08-26

The research layer, and the headline experiment the project was built to run. A
third engine joins the ladder: a 12-billion-parameter instruction model at 4-bit
quantization, served locally through Ollama with its response schema enforced by
the server. The benchmark of spec section 13.4 ran across all three engines on
the test split, and the significance family covers all three engine pairs
corrected together.

**The language model came third.** It lost to both classical engines on macro-F1
and on micro-F1, on every markup-quality tier, and on the seen-locale slice, and
most of those margins are certified by the clustered permutation test after
correction. The one slice where it led the n-gram model is the unseen locale, and
that difference does not survive the correction. The predictions were registered
in `experiments/predictions/p6-llm-comparison.md` before the run; four of the
eight held.

Nothing about the tool's default changed and nothing needs to. The research layer
is optional at runtime, is never required for an audit, and is never exercised by
CI.

### Added

- `src/autofill_audit/llm/client.py`: the `LLMClient` interface of spec section
  12.1, an `OllamaClient` against the OpenAI-compatible `/v1/chat/completions`
  endpoint with a JSON schema passed on every request, a `CloudClient` for the
  hosted config swap, and a transport seam so that every line of the validation
  and retry logic is testable without a network.
- `src/autofill_audit/llm/prompts.py`: `PROMPT_VERSION`, the system prompt of
  spec section 12.2, the response schema with the label `enum` injected from
  `taxonomy.py` at request time, and the descriptor pruning that drops geometry,
  framework attributes and the declared `autocomplete` value.
- `src/autofill_audit/classify/llm.py`: the `Classifier` implementation, which
  chunks a page into requests, carries the per-field latency convention, and
  reports `self-reported` as its confidence kind.
- The validation and retry ladder of spec section 12.3: one parse retry carrying
  the parser's error, one semantic retry naming the missing or invented
  selectors, and on a second failure the affected fields scored `UNKNOWN`,
  counted, and kept in the denominator.
- `scripts/bench.py` and `autofill-audit bench`: the multi-engine benchmark,
  which checks every engine's prerequisites before the first page loads and
  assembles the section 13.4 grid from committed metrics documents rather than
  recomputing anything.
- An `llm` block in `thresholds.json`, at zero and zero, because spec section
  12.1 forbids a self-reported confidence from feeding the threshold policy and
  the decision procedure still needs two floats. The consequences are written
  down in `docs/findings.md` and were registered before the run.
- `docs/adr/0007-llm-model-and-quantization.md`: the resolved model, the serving
  route, the observed VRAM headroom, and a bounded keep-alive policy.
- `docs/llm-price-table.md`: the price table spec section 12.4 requires, honest
  about carrying no prices.
- LLM tests against twelve committed transcripts under `tests/fixtures/llm/`,
  including deliberately malformed responses, plus live tests that are marked and
  skipped unless `AUTOFILL_AUDIT_LLM_TESTS=1` and a reachable server agree.
- A third arm in `audit/engine.py::_confidence_display`, so a self-reported
  confidence is never rendered as a bare number beside a calibrated one.

### Changed

- `scripts/analyze.py` accepts `--run` repeatably and builds one comparison
  family over every engine pair, corrected together. The family membership was
  fixed in the prediction file before the runs.
- `eval` and `audit` accept `--engine llm` and the three `--llm-*` flags, and
  `audit` reads an `[llm]` block from the config file.
- Every run-log row now carries `prompt_version`, which is null for the engines
  that have no prompt.
- The README's results section is a three-engine comparison, and every number in
  it links to one of the new run files.
- The golden report snapshots moved, by the version string and nothing else. The
  rule engine renders its own `tool_version` into the JSON and HTML reports, so a
  release bump is a snapshot diff. Ground rule 12 requires that to be an
  intentional, changelogged change rather than a refresh nobody read, and this is
  the entry: nine snapshots, `0.3.1` to `0.4.0`, no other byte changed.

### Fixed

- `load_engine(EngineChoice.LLM)` no longer refuses by naming a future phase. The
  three ways its prerequisites can be missing now produce three different
  messages, because the fixes are different.

### Note on the earlier measurements

The two classical engines reproduced their previous run exactly, every prediction
and every finding, field for field. Only the re-measured latency columns differ.
The earlier result files are untouched and the README no longer cites them.

Every rules-against-ngram adjusted p value is larger in this release's analysis
than in the previous one, because the family tripled. The underlying p values did
not move. This was registered in advance for exactly this reason.

## [0.3.1] - 2026-08-26

The corpus power repair. P5 measured the two engines against each other and then
found that the test split could not certify the difference: the significance test
clusters by template, the test partition held five templates, and a paired
sign-flip permutation over five clusters cannot produce a p value small enough to
reach the pre-registered level, at any effect size. This release widens the
corpus so the design has power, and re-measures everything that depended on it.

Every recorded metric in the repository moves as a result. The reason is written
down in `docs/ENGINEERING_LOG.md` and the predictions are registered in
`experiments/predictions/p5r-power-repair.md`, both committed before the first
template was written. No result file from the previous measurement is edited or
deleted; the README now cites the new runs and the old ones stay as the first,
underpowered measurement.

### Added

- Fifteen new form templates, three per family, structurally distinct from their
  siblings rather than relabelled: they differ in which sections exist, in which
  slots those sections carry, and in how the composite and split cases render.
  They are designed to carry the labels that had no training rows at all.
- A fifth active clause in `scripts/check_reachability.py`: every label a model
  can predict must appear in the train partition with at least a stated minimum
  number of rows. The minimum is one whole training template's worth of a field
  carried in every locale, and the constant carries that derivation beside it.
- `experiments/predictions/p5r-power-repair.md`, committed before the template
  work, registering that the engine ordering persists, that the n-gram engine
  improves in absolute terms, that the primary comparisons now clear the design
  floor so verdicts become certifiable either way, and that page load still
  dominates the wall time.
- New test-split runs for both engines and a new significance analysis over the
  pair, each carrying `p5r` in its run id.

### Changed

- The realised grid is eight templates per family instead of five, and the split
  is five train, one dev, two test per family instead of three, one, one. The
  test partition now holds ten templates, which gives the paired sign-flip test
  one thousand and twenty-four arrangements and a smallest attainable two sided
  p value two orders of magnitude below the pre-registered level.
- The generator version is bumped, because the emitted set of forms changes for
  an unchanged seed. The corpus manifest records the new grid, and the
  determinism contract is unchanged: same seed, same bytes, asserted answer keys,
  and the generate-twice gate run on the new grid.
- The model, its vocabulary, its calibration, its evidence table and its card are
  retrained on the widened train partition and land in one commit, as the
  model-card ground rule requires.
- Both decision thresholds are rederived on the new dev split, through the same
  pre-registered policy and against the same target precision as before. The
  policy is unchanged on purpose: repairing a corpus and moving a threshold in
  the same phase would produce two changes and no way to attribute either.
- The committed sample corpus is regenerated. Its forms and answer keys are
  byte-identical to before, because the sample cells and their seeds did not
  change; its split document and manifest change because the grid did.
- The README cites the new result files throughout.

### Notes

- The statistical policy is untouched: the alpha, the false discovery rate, the
  absolute practical-effect threshold, the clustering unit and the reporting
  minimum are all exactly what P4 and P5 pre-registered.
- The seed is unchanged, and `fr-FR` remains the held-out locale.
- **What the re-measurement found**, in one line each and in full in
  `docs/ENGINEERING_LOG.md`: every comparison is now decidable and none is
  reported as underpowered; all eleven come back as no significant change after
  the family correction; the rule baseline still leads the label-weighted average
  and the model now leads the field-weighted one; the model improved by about a
  third of a point of macro-F1; and the model made its first wrong accusation,
  nine of them, which the changed threshold values explain and which the model
  card and the README both state rather than round.
- Ground rule 12 applies to the threshold values, which moved. They moved because
  the dev split did, not because the policy did, and the movement is a
  consequence of the corpus change registered in advance rather than a retune.

## [0.3.0] - 2026-08-26

The evaluation release. The repository carries measured results for the first
time, and the README carries numbers for the first time, each one a link that CI
follows to a result file, to its manifest, and to a commit.

### Added

- **`autofill-audit eval`** (spec section 14), wrapping `scripts/eval.py`. Takes
  `--corpus`, `--split {dev,test}`, `--engine {rules,ngram}`, `--out` and
  `--run-id`, and refuses `--split test` without `--i-am-measuring`, because the
  test split is spent the first time it is read. `--engine auto` is deliberately
  not offered: a result file whose engine column said `auto` would not say which
  engine produced the number in it.
- `evaluate/metrics.py`: per-label precision, recall and F1 with both counts,
  macro-F1 and micro-F1, per-locale, per-tier, per-family and locale-by-tier
  grids, the held-out-locale slice reported separately, abstention rate and
  accuracy on the non-abstained subset, confusion matrices, calibration with
  expected calibration error reported both including and excluding the twelve
  classes whose calibrator is the identity, latency percentiles, the whole-run
  wall time split into load, extract, classify and render, and finding-level
  precision and recall against the answer key.
- `evaluate/runlog.py`: the JSONL writer at the spec section 13.1 schema, with
  its sibling manifest at spec section 18. Both refuse to overwrite an existing
  file, because result files are append-only history and a wrong result gets a
  new run id rather than a regeneration.
- `evaluate/triage_bridge.py`: the only module permitted to import the external
  evaluation harness, enforced by a test that walks every Python file in the
  repository. It carries the paired permutation clustered by template, the
  Benjamini Hochberg correction across the comparison family, and the three way
  outcome classification with the middle category reported rather than promoted.
- `scripts/analyze.py`: compares two committed run logs through the harness and
  writes the significance analysis as a result file of its own.
- `scripts/check_prediction_ancestry.py` and the `ancestry` make target and CI
  job: law 4 made mechanical. Each prediction file names, in front matter, the
  paths it predicts about, and the check verifies that the commit which added it
  is an ancestor of the commit that last touched each of them. A prediction file
  edited after it was added must declare the edit.
- `experiments/predictions/p5-statistical-policy.md`, committed before any
  test-split run, fixing the procedure, the false discovery level, the practical
  effect threshold and its justification, seven predictions about what the test
  split would show, and the power the design actually has.
- `experiments/results/`: two development sanity runs, two test-split runs, and
  one significance analysis, each with a run log, a manifest, a metrics document,
  a confusion matrix, and the per-field finding-level judgements.
- `docs/cross-repo-tasks.md` now carries what the harness turned out to need,
  with five issues filed on that repository and a concrete API proposal in each.

### Changed

- `scripts/check_traceability.py` gained `--resolve`, which follows every
  citation in the README and in `docs/` to a result file, to a manifest, and to a
  commit this repository can produce, and fails when any step does not resolve.
  A run marked dirty in its manifest fails the same way a missing one does. The
  `traceability` CI job and `make trace` pass the flag.
- The reporting minimum of thirty fields per cell now applies to the
  finding-level rates as well as to the grid cells, judged separately against
  each rate's own denominator. Decided in the pre-registered policy file, before
  the test runs.
- The descriptor cache is bound to the corpus that filled it. A cache built from
  a different corpus is refused rather than silently reused or silently emptied.
- `scripts/train.py` gained `extract_forms` and `examples_for_form` as public
  functions, so the evaluation runner shares one definition of which controls
  become examples rather than growing a second.
- The lock file was regenerated to add the harness and its transitive
  dependencies. No existing pin moved.

### Notes

- The harness is pinned as a git tag reference in the `dev` extra rather than in
  the runtime dependencies. It pulls thirteen transitive packages including
  tensorboard, grpcio, pandas, plotly, pillow and werkzeug, and the audit path
  never imports it. The consequence is that the shipped wheel cannot compute its
  own significance tests. Spec section 0.5 permits a git ref at this phase and
  forbids one at `1.0.0`, and both the publication and the narrower extras are in
  `docs/cross-repo-tasks.md`.
- **The measured result is that the rule baseline beats the n-gram model on every
  slice of the test split.** The default engine is unchanged and no threshold
  moved, so no reported finding changes; what changed is that the README now says
  which engine is better and links to the files that show it.

## [0.2.0] - 2026-08-26

### Added

- **The n-gram classifier.** `--engine ngram` runs a multinomial logistic
  regression over character and word n-grams of a control's text, its intrinsic
  attributes, its option-list shape, and its position, exported to ONNX and
  served on the onnxruntime CPU execution provider with threads pinned.
  `--engine auto` prefers it when a model loads.
- `classify/features.py`: one featurisation, imported by the training script and
  by the inference path alike, with hand-rolled character and word analysers that
  are asserted against scikit-learn's own `char_wb` enumeration. There is no
  second implementation, because train and serve feature skew is the most common
  way a deployed text classifier silently degrades.
- `classify/onnx_model.py`: the session wrapper, the per-class calibration and
  its renormalisation, the bundle loader and its cross-checks, and an evidence
  list that names the n-grams which drove each prediction.
- `scripts/train.py` and `autofill-audit train`, with the test-partition guard
  the specification asks for: every corpus path is checked before it is opened,
  and an audit hook raises on any read of a test-partition file that no check
  covered.
- `scripts/derive_thresholds.py`, which implements the pre-registered threshold
  optimisation and writes the result into the committed threshold document.
- `models/`: the trained model, its fitted vocabulary, its per-class calibration,
  its label map, its evidence table, its development metrics, and its training
  manifest. `docs/model-card.md` lands in the same commit, per ground rule 8.
- `docs/adr/0006-onnx-export-path.md`, recording the export route with the opset
  probe's output, the shape of the graph that resulted, and the parity evidence.
- `experiments/predictions/p4-threshold-derivation.md`, committed before the
  model existed, stating how the thresholds would be computed and what the
  measurement was expected to show.

### Changed

- **The decision thresholds are now derived rather than mapped, for the n-gram
  engine only.** `audit/thresholds.json` grew a block per engine at schema
  version 2. The rule engine's block is byte-identical to what `v0.1.0`
  committed, so no rule-engine finding on any page has moved and no golden
  snapshot churned. The n-gram block was derived on the development split
  against a precision target committed before the measurement, and it records
  the target, the achieved precision and recall, the denominators behind them,
  the corpus manifest sha, and the date.
- An engine with no threshold block is now an error rather than an inheritance.
  Applying one engine's boundary to another engine's confidences would apply a
  scale to numbers produced on a different one, and it would do it silently.
- The `auto` fallback notice now reads "the n-gram model did not load" rather
  than "no trained model is installed". A model that is present and unreadable is
  a different fact from a model that is absent, and the old sentence would have
  been false in the case a user most needs the truth about. The reason follows
  the notice on the same line.
- `autofill-audit version` prints every engine's thresholds rather than one set.
- The `check-added-large-files` pre-commit hook now skips `models/`. The
  committed ONNX file is a weight matrix over the whole feature vocabulary and is
  larger than the hook's ceiling by design.

## [0.1.0] - 2026-08-26

### Added

- Repository foundations: packaging with a console entry point, the source tree
  of the build specification's layout section, and the MIT license.
- `taxonomy.py`, the one definition of the label space: the WHATWG autofill
  field-name tokens adopted as labels, plus the enumerated extra labels for the
  cases the specification does not cover, with their group mapping.
- `autofill-audit version`. `autofill-audit audit` is present but refuses until
  the audit engine lands at P3.
- The six CI jobs: lint, types, test, reachability, traceability, and build,
  each proven capable of failing before being trusted.
- `scripts/check_dashes.py`, `scripts/check_reachability.py`,
  `scripts/check_traceability.py`, and `scripts/check_commit_msg.py`, wired into
  both CI and pre-commit.
- `requirements.lock`, the fully resolved pin set that CI installs from.
- `docs/adr/0001-toolchain-resolution.md` recording the resolved version matrix,
  plus the environment, engineering log, cross-repo task, reference, and CI
  proof documents.

- The corpus generator: five form families of five structurally distinct
  templates each, across six locales and four markup-quality tiers, seeded from
  one seed and deterministic to the byte. Locale profiles are structural rather
  than merely lexical: field order, field presence, name decomposition, and
  address composition differ per locale alongside the label, placeholder, and
  identifier strings.
- Answer keys as separate JSON per form, mapping CSS selector to taxonomy label
  with per-field provenance and the `expected_modifiers` the audit engine needs,
  plus a committed JSON schema generated from the taxonomy.
- `corpus/split.json`: a train, dev, and test split partitioned by template,
  with `fr-FR` held out of training entirely as the unseen-locale slice.
- `corpus/manifest.json`: seed, generator version, the realised grid with
  per-cell counts, a sha256 per form, and the split assignment sha.
- `autofill-audit corpus generate` and `autofill-audit corpus validate`.
- A small committed sample corpus under `tests/fixtures/sample_corpus/`, a
  byte-identical subset of a full run, with `scripts/make_sample_corpus.py` to
  regenerate it.
- `docs/taxonomy.md`, `docs/report.md` carrying the reporting-minimum policy,
  and `docs/adr/0005-held-out-locale.md`.

- The extractor: `descriptors.py` with the `FieldDescriptor` schema and its
  lossless round trip, `loader.py` with the bounded waiting policy,
  `extract/walker.py` with the DOM traversal, `extract/signals.py`,
  `extract/normalize.py`, `extract/selector.py`, `extract/groups.py`, and the
  in-page traversal script `extract/traverse.js`.
- Same-origin frames walked as separate roots, open shadow roots walked in
  place, and closed shadow roots, cross-origin frames, and canvas-only pages
  reported as undetectable rather than passed over in silence.
- Structural group detection: split card expiry as two selects or as a select
  and a text input, address line runs, and radio and checkbox groups by shared
  name, all with a shared group id and an injectable clock for the expiry year
  window.
- `autocomplete` parsing into `DeclaredAutocomplete`, including modifiers,
  `section-*` tokens, `off`, and off-specification detection that distinguishes
  a token HTML does not define from a token this project's taxonomy leaves out.
- Honeypot detection by visibility and bounding box. Hidden controls are
  excluded from the audited fields and retained on the extraction result, so a
  reported field count still matches the markup a developer wrote.
- `ExtractionResult`, the page-level surface: warnings, honeypots, canvas
  regions, the settle report, and the truncation state.
- Seventeen hand-authored extractor fixtures under `tests/fixtures/extract/`,
  each with a header comment saying what it tests and a committed expected
  descriptor list, with `scripts/refresh_fixtures.py` to regenerate them
  deliberately.
- `scripts/corpus_sweep.py`, which extracts every form in a corpus and
  reconciles it against its answer keys.
- `docs/findings.md` with the selector contract, stated once and used
  identically by every consumer. The finding catalogue arrives at P3.

### Changed

- Faker moves from the `dev` extra to the runtime dependency set, because
  `autofill-audit corpus generate` is part of the shipped command surface and
  must work from an installed wheel. `make lock` reproduced the existing lock
  file byte for byte, so no pin moves and there is no lock commit.
- `corpus/selectors.py` gains `nth_of_type_tail`, the anchorless half of a
  positional path, which the extractor needs inside a shadow root where the root
  itself is the anchor and has no selector. `nth_of_type_path` is rewritten in
  terms of it so there is still one implementation of the join.
- `extract/normalize.py` inserts token boundaries on both sides of the case
  fold rather than only before it. Case folding does not always produce
  lowercase: Cherokee folds to uppercase, so a folded token could still carry a
  case transition that the boundary pass never saw, and a second pass over the
  same text returned a different answer. Also found by the idempotence property.
- `extract/normalize.py`'s token splitter no longer treats Unicode combining
  marks as delimiters. Python's word class excludes them, so a splitter built on
  it shreds every decomposed form and every script that marks its vowels, and it
  broke idempotence outright: casefolding the Turkish dotted capital I yields an
  `i` followed by a combining dot, and splitting on that dot made a second pass
  return something different from the first. Found by the property test spec
  section 15 layer 4 requires.

- `scripts/check_reachability.py` now enforces law 2 clause (b): every taxonomy
  label must be emitted by at least one answer key. The clause left the script's
  pending list in the same commit that made it enforceable.

- **The tool becomes useful.** `autofill-audit audit` reads a page and reports
  which controls a browser's autofill will not recognise and what one-line markup
  change fixes each one.
- The rule baseline: `classify/rules_table.py`, a structured table of pattern,
  label, weight, and signal name, with a multilingual vocabulary covering the six
  corpus locales and a locale tag on every entry whose wording belongs to one
  language. `classify/rules.py` owns the six-tier precedence and no vocabulary of
  its own, so adding a language never touches the engine.
- `classify/base.py`: the `Classifier` protocol every engine implements, and the
  four ordered confidence tiers, whose numeric values are stated once with the
  warning that they are not probabilities and are not calibrated.
- `classify/__init__.py` with `load_engine`, the ladder's one entry point and the
  home of the documented fallback: `--engine auto` uses the strongest engine that
  loads and prints one clear line when it falls back to rules.
- `audit/findings.py`: the finding codes of the specification with their
  severities, triggers, and fix templates, the fix text stored as data beside the
  enum so all three renderers agree by construction, and the documented
  equivalence sets consulted before a mismatch is reported.
- `audit/engine.py`: the ordered decision procedure, at most one primary finding
  per control and any number of independent secondary ones, with configured
  suppressions retained under their own key and a corpus mode whose answer key
  never changes a user-facing finding.
- `audit/thresholds.py` and the committed `audit/thresholds.json`, which carries
  the documented rule-tier band mapping and records that nothing in it has been
  measured. P4 replaces the mapping with thresholds derived on the dev split.
- The three renderers: a `rich` terminal report whose summary is counts and never
  a composite score, a versioned JSON report that is a pure function of the page,
  and a single self-contained HTML report with no external asset and no network
  fetch at view time.
- The full `audit` command surface: `--engine`, `--format`, `--out`, `--fail-on`,
  `--timeout`, `--settle`, `--include-hidden`, `--frames`, `--min-confidence`,
  `--json-schema`, `--config`, and verbosity, with the exit-code contract of the
  specification, where a page that could not be reached is a different code from
  a page that has problems.
- The deliberately absent flags, `--crawl`, `--depth`, `--fill`, `--fix`, and
  `--write`, each answered with the boundary it names and the reason for it
  rather than with an unknown-option error.
- `autofill-audit.toml`, discovered upward from the working directory, with the
  precedence chain flag, environment variable, file, default. Every suppression
  requires a stated reason and appears in the JSON report under `suppressed`.
- Golden report snapshots under `tests/golden/` for a fixed fixture set in all
  three formats, with `scripts/refresh_golden.py` to regenerate them by hand.
  There is no update flag on the test suite, on purpose.
- The false-positive property test: nothing above `info` across the entire
  correct-markup slice of the corpus, generated at test time and audited through
  a real browser. This is the check that decides whether the tool is worth
  installing.
- Two hand-authored fixtures: `checkout_hostile.html`, which reaches almost every
  code in the catalogue, and `checkout_modifiers.html`, whose every declaration
  carries a section modifier and whose correct report is empty.
- `docs/findings.md` grows the finding catalogue: every code with its trigger,
  its severity, its exact fix template, and a before-and-after example, plus the
  equivalence sets, the confidence tiers, the configuration format, and the exit
  codes.

### Changed

- `scripts/check_reachability.py` now enforces all four clauses of law 2. Clause
  (c) reads the rule table itself and the exemption table in `docs/taxonomy.md`;
  clause (d) collects `label` markers from a real pytest collection, which is the
  only way to resolve a marker argument that a parametrised table computes. The
  script's pending list is now empty.
- The browser fixture moves to the root `conftest.py` and is shared by every
  suite. Playwright's synchronous API allows one live session per thread, so two
  session-scoped fixtures each opening one produce an error that reads like an
  async mistake and is nothing of the kind. The end-to-end CLI tests run the tool
  in a subprocess for the same reason, which also makes them a more faithful test
  of the exit codes.
- The `trailing-whitespace` pre-commit hook now skips `tests/golden/`. A golden
  snapshot of terminal output is byte-exact by definition, and `rich` pads a
  table row to the full width; a hook that trimmed those spaces would rewrite the
  committed expectation on every commit.

Note on the link below for `1.0.0`: it compares against `main` rather than
against a tag, because **there is no `v1.0.0` tag**. The reason is in that
release's entry and in `docs/cross-repo-tasks.md`, and the link is written this
way rather than pointing at a tag that does not exist.

[Unreleased]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.4.0...HEAD
[1.0.0]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.4.0...main
[0.4.0]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Olajide-Badejo/autofill-audit/releases/tag/v0.1.0
