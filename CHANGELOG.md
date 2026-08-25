# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

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

[Unreleased]: https://github.com/Olajide-Badejo/autofill-audit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Olajide-Badejo/autofill-audit/releases/tag/v0.1.0
