# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- `extract/normalize.py`'s token splitter no longer treats Unicode combining
  marks as delimiters. Python's word class excludes them, so a splitter built on
  it shreds every decomposed form and every script that marks its vowels, and it
  broke idempotence outright: casefolding the Turkish dotted capital I yields an
  `i` followed by a combining dot, and splitting on that dot made a second pass
  return something different from the first. Found by the property test spec
  section 15 layer 4 requires.

- `scripts/check_reachability.py` now enforces law 2 clause (b): every taxonomy
  label must be emitted by at least one answer key. The clause left the script's
  pending list in the same commit that made it enforceable. Clauses (c) and (d)
  remain staged for P3.

[Unreleased]: https://github.com/Olajide-Badejo/autofill-audit/commits/main
