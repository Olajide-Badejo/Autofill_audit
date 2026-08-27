# ADR 0004: ML-Experiment-Triage stays external

Date: 2026-08-27
Status: accepted
Phase: P5

**Recorded at P7.** The decision was made at P0, when the dependency was
deliberately left out of `pyproject.toml` until something imported it, and it was
acted on at P5, when the harness was integrated across the package boundary and
the friction it exposed was filed as five issues. The ADR was missed at both
points and is written here from the recorded evidence: the ledger in
[`../cross-repo-tasks.md`](../cross-repo-tasks.md) with its five issue links, the
`dev`-extra placement and its comment in
[`../../pyproject.toml`](../../pyproject.toml), the mypy override in the same
file, the `harness` and `harness_cross_check` blocks in every committed
`analysis.json`, and the P0 and P5 entries in
[`../ENGINEERING_LOG.md`](../ENGINEERING_LOG.md). The lateness is a defect and
this note is the record of it.

## Context

This project needs three statistical capabilities: a permutation p value, a
Benjamini and Hochberg step-up correction, and a verdict vocabulary that keeps a
*significant but below the practical threshold* category rather than collapsing
it.

All three already exist in `ML-Experiment-Triage`, an evaluation harness the same
author built earlier and released. Two options:

**Vendor them.** Copy four functions into a `stats.py` here and move on. It is
half an hour of work, it removes a dependency, it removes a packaging blocker,
and nobody reviewing the repository would object.

**Consume the package across a real boundary.** Pin it, import only its public
API, and file an issue on that repository whenever it does not fit.

## Decision

**`ML-Experiment-Triage` is a dependency, not a component.** It is not vendored,
not submoduled, and not copied file by file into `src/`.

The claim being made is specific and it is the reason the expensive option was
taken:

> A piece of infrastructure that has exactly one consumer has not been shown to
> be infrastructure. It has been shown to be part of that one program.

That harness was built as a general evaluation harness. Until a second,
independently designed project depends on it across a package boundary and finds
its API sufficient, the generality is an assertion. **This project is the second
consumer, and the friction it discovers is the actual finding.** Vendoring the
code would destroy that evidence by making the boundary unobservable.

### The contract, binding in both directions

- This repository writes run logs in its own schema and never post-processes them
  into a harness-specific shape at the last moment. If the two schemas disagree,
  one of them is wrong and gets changed on purpose.
- This repository never monkey-patches, subclasses around, or reaches into
  internals. Public API only. `evaluate/triage_bridge.py` is the sole importer
  and `tests/unit/test_triage_bridge.py` walks every Python file under `src/`,
  `scripts/` and `tests/` and fails if a second importer appears.
- Anything the harness needs is changed **there**, as a versioned release, and
  recorded in `docs/cross-repo-tasks.md` with the issue link, the release it
  landed in, and the resulting constraint change here.
- **`v1.0.0` may not be tagged here while any dependency is a git ref rather than
  a released version.** That is a gate criterion, not a preference.
- At P7 the other side of the link is added: that repository's README gains a
  *Used by* entry pointing here. Cross-linking is what makes the second-consumer
  claim checkable by a reader who lands on either repository alone.

## Consequences

**The split ran cleanly through the middle of the package, and where it ran is
the result.** The statistical primitives fit exactly and were used unchanged. The
data model, the ingestion layer and the comparison entry points did not fit at
all, because they model a training run observed over time and this project
measures a set of items observed once.

The parts built around the *statistics* generalised. The parts built around the
*shape of a training run* did not, and they did not because the shape was never a
statistical assumption in the first place. It was the shape of the one program
the package was extracted from. That is a sharper finding than either "it worked"
or "it did not".

**Five issues are open**, each with a concrete API proposal: cross-sectional run
log ingestion, clustered and paired permutation, an absolute practical-effect
threshold, a stable join key on the verdict output, and a packaging pair covering
the typing marker and an extras split. The ledger carries them.

**Two workarounds stand here in the meantime and both are labelled in every
result file they produce.** The clustered null is built in
`evaluate/triage_bridge.py` and handed to the harness's p value estimator; the
practical-effect gate is applied here because the harness's is relative where
this project pre-registered an absolute one. A workaround that is invisible in
the output is indistinguishable from a capability, so `analysis.json` carries a
`harness.not_used_for` block naming both.

**The anticipated friction was aimed one layer too low, and the miss is recorded
rather than rewritten.** The ledger predicted, before P5 began, that
categorical-outcome support in the permutation machinery would be the problem. It
was not needed at all: `permutation_p_value` never sees an outcome, only an
effect and a null, both floats. The categorical part of the problem lives
entirely in the statistic and the statistic is the caller's.

**The harness is a `dev` dependency, not a runtime one, and the cost is stated
rather than discovered.** Installing it pulls thirteen transitive packages
including a training-metrics logging stack, and the audit path never imports it.
A `pipx install` that dragged that onto a developer's machine so that a command
they will never run could compute a permutation p value would be the wrong trade.
The consequence is that **the shipped wheel cannot compute its own significance
tests.**

**Strict type checking cannot see inside it.** The package ships no typing
marker, so every value crossing the boundary arrives as `Any`. That is a real
cost of the boundary and it is recorded as one: the bridge is the one module in
`src/` whose external calls are unchecked, which is another reason for it to be
the only module that makes them. The override in `pyproject.toml` configures this
project's checker; it does not change the dependency.

**This decision is the reason `v1.0.0` is not tagged at P7.** The package is not
published on a package index, the dependency is therefore a git ref, and the rule
above forbids the tag. The rule was written on the first day of the project,
before it was inconvenient, and it holds now that it is. The cheap way out is
still available and is still refused: vendoring the three functions would remove
the blocker and would delete the evidence the boundary exists to produce.
