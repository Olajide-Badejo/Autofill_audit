# Engineering log

Dated, append-only. Every gate, every surprise, every reverted decision. Written
as the work happens rather than reconstructed later, because the reports at P7
draw on this file and reconstruction from memory is both slower and less honest.

Newest entries go at the bottom.

## 2026-08-25: P0, foundations

### What was resolved

The toolchain matrix, in full, on the target machine. It is recorded in
[`adr/0001-toolchain-resolution.md`](adr/0001-toolchain-resolution.md) rather
than repeated here.

The headline is that the interpreter did not have to be held back. The
specification anticipated the four-way intersection of Playwright,
scikit-learn, onnxruntime, and the evaluation harness landing one CPython minor
behind the newest stable, since onnxruntime is usually the last of the four to
publish wheels. It did not: onnxruntime ships `cp314` wheels, so the pin is the
newest stable CPython and nothing was worked around.

Also resolved and recorded in the same ADR: click over typer, Make over just,
pip-compile over uv, and latexmk over tectonic. The last of these is the
specification's stated fallback condition rather than its stated preference, and
it applies because this machine already carries a full TeX Live installation.

### Surprises

**Passwordless sudo, so the Playwright dependency fallback was not needed.**
The specification plans for `playwright install chromium --with-deps` being
refused for lack of root, with a manual system library list recorded in
`environment.md` as the fallback. Root was available, the flag worked, and the
libraries installed cleanly. The fallback list is therefore deliberately *not*
written down: recording a list that was never exercised would invite somebody to
follow it later and install the wrong set.

**The evaluation harness is not on PyPI.** Discovered while deciding whether to
put it in `pyproject.toml` at P0. It exists only as a GitHub repository. Since
tagging a stable release here is forbidden while any dependency is a git
reference, publishing it is a blocking cross-repo task rather than a detail, and
it is filed as such in [`cross-repo-tasks.md`](cross-repo-tasks.md) with status
open. The dependency is deliberately absent from `pyproject.toml` until P5, so
that the lock file does not carry something nothing imports.

**The dash check had to be written so it could survive itself.** The first draft
of `scripts/check_dashes.py` declared its two forbidden characters as string
literals, which made the file an immediate violation of the rule it enforces.
They are now built with `chr()`. The same reasoning applies to
`scripts/check_commit_msg.py`, whose blocklist would otherwise have been the one
file in the repository carrying every string the repository forbids; its
patterns are stored base64 encoded and decoded at import. Two tests do the same
thing for the same reason. This is a small point but it is a real one: a checker
that cannot pass its own check is a checker that gets an exemption, and an
exemption is where enforcement starts to rot.

**Docstring-only placeholders had to be genuinely statement-free.** The module
skeleton was first written with `from __future__ import annotations` in every
placeholder. That is one executable statement per file, thirty of them, none
ever imported, which pushed measured coverage of the library well under the
gate for no reason connected to the code that actually exists. Stripping the
import leaves the placeholders with zero statements, which is what the coverage
gate should see: the phases that fill them bring their own tests.

### Decisions taken inside P0 that the specification left open

- **`requires-python` is `>=3.14`**, not a wider floor. It is the only
  interpreter CI exercises, and claiming support for versions nothing tests is
  the kind of small dishonesty that this project's laws exist to rule out.
  Widening it is a later decision that arrives with a CI matrix entry.
- **The reachability check does more than the task required.** Beyond the
  taxonomy self-consistency checks it also scans `src/` and `scripts/` for label
  strings written as literals outside the taxonomy module, which is ground rule
  6 made mechanical. The scan is limited at P0 to tokens that cannot be confused
  with ordinary prose, meaning the hyphenated specification tokens and the
  uppercase extras; `name`, `email`, `tel`, and `url` are excluded because a
  check that cries wolf is a check somebody turns off.
- **The traceability check states its rule positively.** Rather than flagging
  every numeric literal and then excusing most of them, it flags three
  measurement shapes: a percentage, a probability-shaped decimal, and a number
  sharing a line with a measurement word. Years, ISO dates, version strings,
  reference numbers, list markers, code blocks, and URLs are never flagged at
  all. A line is cleared either by a result-file reference or by an explicit
  annotation carrying a written reason. The alternative design, flag everything
  and maintain an exclusion list, was rejected because the exclusion list grows
  until the check means nothing.

### Deviations from the build specification, recorded rather than absorbed

- **`report_for_me/` is local only and is gitignored.** The specification lists
  the personal archival report as a committed deliverable, source and PDF both.
  The author's instruction overrides that: it is written for the author, with
  the context gone, and it stays on the machine. The other two reports, the
  public main report and the debug report, are unaffected and are still
  committed at P7. Noted here because a reader of the definition-of-done
  checklist would otherwise find one box that can never be ticked.
- **A first remote was created and then abandoned.** The repository was
  initially pushed to a remote whose name differed in case and separator from
  the one the author wanted. The remote was repointed before any run URL was
  recorded, so nothing in `ci-proof.md` refers to the abandoned repository. The
  abandoned one is left in place rather than deleted, because the credentials in
  use do not carry delete scope.

### Gates

Recorded here as they were run, with the CI run links in
[`ci-proof.md`](ci-proof.md).

- Local gates: `make gates`, which is ruff check, ruff format, the dash check,
  mypy strict, pytest with the coverage gate, reachability, and traceability, in
  the order CI runs them. All green. Measured library coverage came out at the
  ceiling, which is unsurprising when the library is a taxonomy, a small CLI,
  and a set of statement-free placeholders.
- Wheel and sdist built, the wheel installed into a pipx environment of its own,
  and the installed command run.
- All six CI jobs green on `main`.
- All six CI jobs observed red, one per scratch branch, each from a single
  deliberate change, with the run links and the failure text recorded. Branches
  deleted afterwards.

Two things came out of the proof-of-failure exercise that were worth having.
The build job's first attempt was itself broken: it assumed pipx would place
the console script at a fixed path, which is a guess and was wrong on the
runner. The job now sets its own pipx home and bin directory, which both fixes
the assumption and gives the wheel a genuinely clean environment to install
into. Separately, the deliberate taxonomy breakage failed both the reachability
job and the test job, which is the correct outcome: the property is asserted in
two independent places on purpose, and a defect that only one of them noticed
would mean the other was not doing its job.

### What P1 needs to know

- The taxonomy is complete and frozen at the specification's token set plus the
  five extras. `GROUPS` partitions it. Import everything from
  `src/autofill_audit/taxonomy.py` and nowhere else, because the reachability
  check now fails the build on a label string written anywhere else in `src/` or
  `scripts/`.
- `scripts/check_reachability.py` is written to be extended rather than
  rewritten: add a function returning a `CheckResult` and register it in
  `CHECKS`. The three clauses that are not yet enforceable are listed in
  `PENDING`, each naming the phase that activates it. Move a clause out of
  `PENDING` and into `CHECKS` in the same commit that makes it enforceable.
- The corpus directory is gitignored except for the sample corpus and the
  manifest. The ignore rules for those exemptions are already in `.gitignore`.
- The lock file is regenerated only by `make lock`, as its own commit with a
  changelog note.
- Faker is a `dev` dependency, not a runtime one. The generator runs from a
  checkout, never from an installed wheel, which is why it does not need to be.

## 2026-08-25: P1, taxonomy and corpus

### Faker becomes a runtime dependency, reversing a P0 note

P0 closed with the note that Faker is a `dev` dependency because "the generator
runs from a checkout, never from an installed wheel". That was wrong, and the
error only becomes visible once the command surface of spec section 14 is
actually wired up: `autofill-audit corpus generate` is a documented subcommand
of the shipped console entry point. A documented command that raises an import
error on a `pipx`-installed wheel is worse for a user than one extra dependency
is for the wheel, and the alternative (a lazy import with a graceful refusal)
buys a smaller wheel at the cost of a code path that only ever runs on a
misconfigured install.

Faker moves to the runtime dependency set. `make lock` was run afterwards, per
spec section 18, and produced a byte-identical lock file: the lock is compiled
with the `dev` extra already, so it carried Faker at this exact pin, and
pip-compile annotates both cases as `via autofill-audit (pyproject.toml)`. There
is therefore no lock commit, which is the right outcome rather than a skipped
step, since regenerating a lock that does not change should not create one.

### The corpus design as built

The template is the atom of the split, so the template had to become the atom of
the generator too. Five families, five structurally distinct templates each,
instantiated across six locales and four tiers. A template asks for a name block
or an address block *by style*; the locale profile decides which slots that
style expands to and in what order. A template that listed address line one and
address line two directly would silently assert that every locale composes an
address the same way, which is the failure spec section 8.1 names.

The locale profiles are the substance of the phase. Each carries label,
placeholder, and identifier strings; which slots exist; what order they appear
in; and how names decompose. German and French address blocks carry no
administrative-area field at all. Japanese leads with the postal code and adds a
kana name pair. Nigerian postal codes are frequently absent, expressed as a
presence probability rather than a flat absence, because "frequently" is the
honest shape of that fact.

### Surprises

**Faker covered every locale, including the one the plan expected to be thin.**
The orchestrator's plan anticipated hand-authored fallback tables for `en-NG`.
The probe at the top of the phase found working providers for names, streets,
cities, administrative areas, and companies in all six locales, and the kana
name providers Japanese needs. The hand-authored tables still exist and still
matter, but for a different reason than expected: Faker generates values, not
interface text, and no provider knows that a German form says *PLZ* and names
the field `plz`. That table is the locale profile, and it was always going to be
hand written. The status table in `taxonomy.md` records what came from where.

**A module named `locales.py` shadowed the `locales/` data directory.** Spec
section 6 names the data directory `locales/`, and the obvious name for the
module that loads it was `locales.py` beside it. Importing
`autofill_audit.corpus.locales` then resolves to the module, and
`resources.files` on it walked one level too high and looked for the tables in
the package root. The module is `profiles.py` now, the directory keeps the name
the specification gives it, and the reason is recorded in the module docstring
so nobody renames it back.

**A dataclass with a parent pointer cannot have a generated `__eq__`.** The
small HTML tree used to check selectors gave every element a `parent`, and
`list.index` during `:nth-of-type` resolution compared two elements, which
recursed up and down the tree until the stack ran out. Elements are identity
objects; `eq=False` is the fix and the docstring says why.

**The mixed tier could produce a form with no clean section.** The draw forces
at least one hostile section and at least one clean one. The clean pass looked
for a section that was not hostile, and when every section had drawn hostile
there was no such candidate, so it silently did nothing and the form came out
uniformly hostile under a mixed label. It surfaced on two templates out of
twenty-five, which is exactly the frequency at which a defect gets shipped. A
section may now be promoted to clean unless it is the only hostile one, and
because a template is required to carry at least two sections there is always a
legal choice. The parametrised test covers all twenty-five templates rather than
a sample, which is how it was caught.

**A shared Faker instance was a latent determinism defect.** The first
implementation cached one Faker per locale and reseeded it per form, which is
safe only while exactly one value provider is alive at a time. Nothing in the
current call path breaks that, which is what made it dangerous: it would have
broken the same-seed-same-bytes rule silently, the first time a caller built two
forms at once.
Constructing a Faker costs well under a millisecond, so each provider now owns
one and the whole grid pays a fraction of a second for an invariant that cannot
be broken from outside. Found by a test asserting that two providers built with
the same seed produce the same value, which they did not.

### Decisions worth recording

**The per-form seed includes the template id.** Spec section 8.1 writes the axis
tuple as family, locale, tier, variant. With five templates per family, two
templates of one family at the same locale, tier, and variant would draw the
same seed and therefore the same sample values. The template id joins the digest
input and the family stays in it, so the input is a superset of the
specification's rather than a replacement.

**The expiry year window is an explicit input, not the clock.** A card expiry
select has to offer years near the present, and spec section 9.5 has the
extractor detect the pair against the current year, so a hardcoded window would
expire. The base year is a generator argument defaulting to the current year and
recorded in the manifest. The corpus is a deterministic function of the seed and
the base year together, and passing the manifest's base year back reproduces the
bytes exactly, indefinitely. The reachability check and the committed sample
both pin it, so neither goes red when the year turns.

**Held-out-locale forms of training templates go to a fourth partition.** The
specification leaves this open. A French form whose template is in train cannot
go to train, because the locale is held out, and must not go to dev or test,
because its template is a training template and that would leak the convention
the split exists to separate. It goes to `excluded`: generated, recorded, and
used by nothing. The reported unseen-locale slice is the French forms in dev and
test, which are clean on both axes.

**The second selector preference uses a descendant combinator.** Spec section
9.3 sketches it as `form[name] > [name="..."]`. A literal child combinator only
matches a control that is an immediate child of the form element, and every form
this generator emits wraps controls in layout containers, so it would produce
selectors that resolve to nothing. The deviation is recorded in
`selectors.py` and in the notes for P2, because the extractor has to reproduce
this exactly rather than approximately.

**Selector resolution is checked without a browser.** An answer key whose
selectors do not resolve is worse than no answer key: every downstream
measurement silently loses the fields it could not find, and the loss looks like
a classifier failure. P2 has a browser; requiring one here would couple P1's
gate to P2's dependency and stop the reachability job from being able to check
anything. The subset of CSS this generator emits is small and fully known, so
`domcheck.py` resolves exactly that subset and raises on anything else, rather
than quietly returning no match for syntax it does not understand.

**Faker moved to the runtime dependency set**, reversing a P0 note, because
`corpus generate` is part of the shipped command surface. Recorded at the top of
this entry.

### Gate

- `corpus generate --seed 20260825 --out corpus/` run twice, `diff -r` of the
  two outputs empty. Shown in the phase output.
- Realised grid: five families of five templates, six locales, four tiers, one
  variant. Well above the floor spec section 8.5 sets. Counts are in
  `corpus/manifest.json`, not repeated here, per spec section 8.5 and law 3.
- `corpus validate` green over the full generated corpus, over the committed
  sample, and over a narrow corpus in the test suite. Every key validates
  against the committed schema.
- Every label in the taxonomy is emitted by at least one answer key. The
  coverage table prints with nothing missing.
- `check_reachability.py` green with clause (b) active. It left `PENDING` in the
  commit that made it enforceable, per the P0 handoff.
- `make gates` green: ruff, the dash check, mypy strict, pytest with the
  coverage gate, reachability, traceability. Library coverage is comfortably
  above the gate.

### What surprised me about the hostile tier

It is graded rather than uniformly impossible, and that turned out to matter
more than expected. Half its controls carry the label text as a placeholder,
which is the placeholder-as-label antipattern and is genuinely classifiable. The
other half carry no text signal at all and leave only the identifier, which is
where the cross-locale claim is actually tested, since the identifiers are
localised. One control per form is deliberately undeterminable, and predicting
`UNKNOWN` on it is the correct answer rather than a failure. If every hostile
control were equally hopeless the tier would measure nothing except that the
tier is hard.
