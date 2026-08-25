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
