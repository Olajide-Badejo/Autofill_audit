# Contributing

Thank you for looking. This repository has rules that are unusual, and most of
them are enforced by a script rather than by review, so it is worth reading this
before you spend an evening on a change that a gate will reject.

## The most valuable contribution

**A false positive.** A page where the tool accused a field it should not have.

The output of this tool is a list of accusations about somebody else's markup. A
wrong finding costs a developer time and costs this project its credibility, and
false positives are the thing the tool is ultimately judged on. There is an issue
template for exactly this and it is the one that gets attention first.

A useful false positive report carries a minimal HTML snippet that reproduces it.
Please do not paste a real page: reduce it to the smallest markup that still
produces the wrong finding, and replace any real values with obviously invented
ones. See the data rule below.

False negatives, new locales and ordinary bugs have templates too.

## The four laws

These four sentences are the whole design compressed. Every argument in this
repository eventually resolves to one of them, and each is a script rather than a
paragraph.

1. **No silent misclassification.** Every classification the tool acts on carries
   a confidence and a named evidence set. Below the reported threshold the tool
   emits `LOW_CONFIDENCE` or `UNDETECTABLE_FIELD` rather than guessing quietly.
   There is no third option, and in particular no path by which a rule table's
   default branch becomes a confident answer.

2. **Reachability.** No label may exist in the taxonomy unless it is a WHATWG
   autofill token or one of the enumerated extras, *and* is emitted by at least
   one corpus answer key, *and* is reachable by at least one rule or present in
   the model's training distribution, *and* is asserted by at least one test.
   `scripts/check_reachability.py` enforces this in CI and reads the taxonomy
   from one source file so the check cannot drift from the code.

3. **Traceability.** No number appears in the README, in `docs/`, in any report,
   or in any plot unless it is reproducible from a committed file under
   `experiments/results/` whose manifest resolves to a real commit in this
   repository. **Hand-typed numbers are forbidden.**
   `scripts/check_traceability.py --resolve` walks the whole chain: the cited
   path must exist, a manifest must sit beside it or above it, that manifest must
   name a commit this repository can produce an object for, and it must not mark
   the run dirty.

4. **Honest measurement.** Estimated or simulated values are labelled as
   estimates at the point of display. Predictions about what a measurement will
   show are committed to git *before* the measurement is taken, and
   `scripts/check_prediction_ancestry.py` verifies that the prediction commit is
   an ancestor of the result commit.

## The rules that will surprise you

### No em dashes, no en dashes, anywhere

The characters U+2014 and U+2013 appear nowhere in this project: not in code,
comments, docstrings, documentation, READMEs, reports, LaTeX sources, commit
messages, issue templates, or generated HTML. Use a comma, a colon, a period and
a new sentence, or parentheses; for ranges use a plain hyphen or the word "to".
Ordinary hyphens are fine.

**In `.tex` sources the ligature forms `--` and `---` are equally forbidden**,
because LaTeX typesets them to exactly the two characters the rule bans. The
reports need to show command line flags, and the resolution is in
`report/preamble.tex`: a macro that puts an empty group between the two hyphens,
so the source never carries the adjacent pair and the page carries two hyphen
glyphs.

`scripts/check_dashes.py` enforces the whole rule over every tracked file, and a
commit-message hook enforces it on messages.

### No attribution artifacts

No document, comment, report, changelog entry or commit message anywhere in this
repository refers to an AI assistant, and no commit carries an AI co-author
trailer. A commit-message hook enforces the message half; the rest is review.

### Synthetic data only, and obviously synthetic

No real name, address, phone number, email, or card number enters this
repository, including the author's own. Demo profiles use names and addresses
that are self-evidently invented; card fields use the officially published test
numbers. A reviewer must be able to tell at a glance that no personal data is
present.

This applies to issue reports too. Reduce a page to the smallest markup that
reproduces the problem and replace real values with invented ones.

### Nothing is regenerated to fix a number

Result files under `experiments/results/` are append-only history. If a result is
wrong, a new run is made with a new run id and the old one stays. Two obsolete
pairs of test-split runs are in this repository for exactly that reason, and the
honest description of them is what they are rather than something to be tidied
away.

The same rule is why a defect found in the evaluation runner after the headline
benchmark was written down rather than fixed in the phase that found it: changing
what the runner does for every engine after seeing the results is a regeneration.

### Findings are additive, never silently retuned

Changing a threshold, a rule, or a severity changes reported findings on real
pages. Any such change is a CHANGELOG entry and, if it changes measured metrics,
a prediction committed before the re-measurement.

## The phase gate discipline

Work happens on a branch named for its phase, branched from `main`, and merges
only after the gate passes **with its output shown**.

> A gate passes when its output is shown. "The tests pass" is not a gate. Pasting
> the terminal output of the gate command is a gate. A gate that cannot be
> demonstrated has not been met.

That discipline is why every CI job in this repository has been observed failing,
one per scratch branch, with the run links recorded in
[`docs/ci-proof.md`](docs/ci-proof.md). A gate that has only ever been green is
indistinguishable from a gate that always returns green.

## Setting up

Everything runs inside a virtual environment, and the commit hooks run the tools
out of it on purpose, so that a local result and a CI result cannot drift.

```bash
python -m venv ~/.venvs/autofill-audit
. ~/.venvs/autofill-audit/bin/activate
pip install -e ".[dev,llm]"
playwright install chromium --with-deps
pre-commit install --install-hooks
pre-commit install --hook-type commit-msg
```

**The virtual environment must be active when you commit.** With it inactive the
hooks fail to find their entry points rather than silently passing.

## Running the gates

`make gates` runs the six checks in the order CI runs them, so a red gate here is
the same red gate there.

```bash
make gates      # lint, dashes, types, tests with coverage, reachability, traceability, ancestry
make lint
make type
make test
make reach
make trace
make ancestry
make dashes
```

Other targets:

```bash
make build          # wheel and sdist
make lock           # regenerate requirements.lock; a deliberate commit with a CHANGELOG note
make tables         # regenerate the report tables and figures from committed result files
make reports        # build all three LaTeX reports
make reports-clean  # remove everything `make reports` produces, so a rebuild starts from nothing
```

`make reports` needs a TeX installation with `latexmk`. The report engine
resolved for this project is recorded in
[`docs/adr/0001-toolchain-resolution.md`](docs/adr/0001-toolchain-resolution.md).

## Things that will fail your commit

- A number in prose with no result-file citation beside it.
- A forbidden dash character anywhere, or two adjacent hyphens in a `.tex` file.
- A taxonomy label string written outside `src/autofill_audit/taxonomy.py`.
- A citation of a result file that does not exist, has no manifest, or whose
  manifest marks the run dirty.
- A result file committed before the prediction file that predicts about it.
- A model binary committed without its model card in the same commit.
- Coverage on library code below the gate.
- A golden snapshot that changed without the diff being read. Refresh with
  `scripts/refresh_golden.py`, read the diff, and put it in the changelog.
- Editing the language model system prompt without bumping `PROMPT_VERSION`. A
  test pins a digest of the assembled prompt and schema, and updating the literal
  alone is the one thing that test exists to prevent.

## Adding a locale

The locale profiles under `src/autofill_audit/corpus/locales/` are hand written
and are the substance of the multilingual claim, so adding one is real work
rather than a configuration change. A profile carries label text, placeholder
text and identifier strings; which address and name slots exist; the order they
appear in; and how personal names decompose.

Adding a locale changes the corpus, which changes the corpus manifest digest,
which invalidates the descriptor cache, the model, its calibration, both derived
thresholds and every recorded metric. That is a whole phase with a prediction
file in front of it, not a pull request. Open an issue with the new-locale
template first and we will work out the sequencing.

## Adding a label

You almost certainly cannot. The label space is the WHATWG autofill token set
plus five enumerated extras, and the reasoning is in
[`docs/adr/0002-taxonomy-is-the-autocomplete-spec.md`](docs/adr/0002-taxonomy-is-the-autocomplete-spec.md).
If the token set grows, this project follows it. If you want a category the token
set does not have, it becomes an enumerated extra with a written justification in
`docs/taxonomy.md`, or it does not exist.

## License

By contributing you agree that your contribution is licensed under the MIT
license, the same as the rest of the project.
