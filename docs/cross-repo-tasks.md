# Cross-repo tasks

The ledger for the dependency contract with
[ML-Experiment-Triage](https://github.com/Olajide-Badejo/ML-Experiment-Triage).

That package is consumed here as an ordinary released dependency. It is not
vendored, not submoduled, and not copied file by file into `src/`. The reasoning
is in the build specification and in the README: a piece of infrastructure with
exactly one consumer has not been shown to be infrastructure, this project is
its second consumer across a real package boundary, and the friction that
boundary exposes is the finding. Vendoring the code would delete the evidence by
making the boundary unobservable.

Two rules make the ledger binding rather than decorative.

- Anything that package needs is changed **there**, as a versioned release, and
  recorded here with the issue link, the release it landed in, and the resulting
  constraint change in `pyproject.toml`. No monkey-patching, no subclassing
  around a limitation, no reaching into internals, no reshaping this project's
  run logs at the last moment to fit an API that does not quite fit.
- `v1.0.0` may not be tagged here while any dependency is a git reference rather
  than a released version.

---

## What P5 found

P5 is the phase that used the package for the first time, on `v1.0.0` installed
from its git tag. This section is the phase's actual deliverable, so it is
written out rather than summarised into a table.

**The single sentence.** The package's statistical primitives fit this project
exactly and are used unchanged; its data model, its ingestion layer and its
comparison entry points do not fit at all, because they model a training run
observed over time and this project measures a set of items observed once.

That split runs cleanly through the middle of the package, and it is a more
interesting result than either "it worked" or "it did not". The parts built
around the *statistics* generalised. The parts built around the *shape of a
training run* did not, and they did not because the shape was never a statistical
assumption in the first place. It was the shape of the one program the package
was extracted from.

### Used unchanged, and they fit exactly

| What | Where | Why it fit |
|---|---|---|
| `permutation_p_value(observed, null, exact)` | `triage.analysis.comparison` | It takes the null distribution as an argument. That is the seam a caller with its own resampling scheme needs, and it means the add-one correction of Phipson and Smyth is computed by that package rather than reimplemented on this side. |
| `benjamini_hochberg(p_values, fdr)` | `triage.analysis.regression` | Spec section 13.3 asks for a step-up correction across the comparison family and this is one, with no assumption about where the p values came from. |
| `classify(results, RegressionConfig)` and the `VERDICT_*` vocabulary | `triage.analysis.regression` | Spec section 13.3 point 4 demands a three way outcome in which the middle category is not dropped. That vocabulary is here already, plus a fourth verdict for a design whose smallest attainable p value is above alpha, which turned out to be the category every primary comparison in this project lands in. Used as a cross check rather than as the decision, for the reason in the third task below. |

`evaluate/triage_bridge.py` is the only module in this repository that imports
any of it, and `tests/unit/test_triage_bridge.py` walks every Python file under
`src/`, `scripts/` and `tests/` and fails if a second importer appears.

### Did not fit, filed, and worked around here in the meantime

Every entry below has an issue on that repository with a concrete API proposal.
None was worked around by monkey-patching, subclassing around, or reaching into a
private name. The bridge imports six public names and nothing else.

## Open

| Task | Issue | Why it blocks | Status | Landed in | Constraint here |
|---|---|---|---|---|---|
| Publish `ml-experiment-triage` to PyPI | [packaging half in #5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | The package exists only as a GitHub repository. Spec section 0.5 permits a git ref at P5 and forbids one at this project's `v1.0.0`, so publication is a hard blocker on the first stable release here. | open | not yet | `ml-experiment-triage @ git+...@v1.0.0` in the `dev` extra of `pyproject.toml`, added at P5 | <!-- traceability: a specification section number and an issue number, neither a measurement -->
| Ingestion of a cross-sectional run log | [#1](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/1) | `JsonlParser` claims a spec section 13.1 run log and then refuses it: `records carry no step field; expected one of step, global_step, iteration, iter, epoch`. There is no step to add. The file has one row per classified field and no time axis, and inventing a step from the row index would let `compare_window_block` treat a set of unrelated fields as a stationary process. | open | not yet | none; the bridge reads its own JSONL |
| Paired permutation with clustered resampling | [#2](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/2) | Spec section 13.3 calls clustering non-negotiable, and no public entry point accepts a cluster assignment. Both comparison modes are also unpaired, and both reduce a metric series to a final window mean, which a categorical per-field outcome does not have. | open | not yet | none; the null is built here and handed to `permutation_p_value` |
| An absolute practical-effect threshold | [#3](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/3) | `RegressionConfig.practical_threshold_pct` is a relative percentage. This project pre-registered an absolute difference of two hundredths of a point of macro-F1, and a relative gate turns one pre-registered rule into a different rule in every slice. | open | not yet | none; the practical gate is applied here and `classify` runs alongside as a visible cross check | <!-- traceability: an issue number beside the words macro-F1, not a measurement -->
| `classify()` reorders its output | [#4](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/4) | It returns `rank(findings)`, and `Finding.tag` is not unique when one metric is compared across several slices, which is exactly this project's family. A positional zip attaches every verdict to the wrong comparison and nothing raises. | open | not yet | none; the bridge rejoins on `id(finding.result)` |
| Ship `py.typed` | [#5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | Without the marker, `mypy --strict` refuses to look inside the package and every value crossing the boundary arrives as `Any`. The source is thoroughly annotated, so the marker is the whole fix. | open | not yet | `[[tool.mypy.overrides]] module = ["triage.*"]` with `ignore_missing_imports` in `pyproject.toml` |
| Split the ingestion and report dependencies into extras | [#5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | Installing it pulls thirteen transitive packages including tensorboard, grpcio, pandas, plotly, pillow and werkzeug, for a consumer that uses three functions. A `pipx install autofill-audit` that dragged a training-metrics logging stack onto a developer's machine would be the wrong trade. | open | not yet | the dependency sits in the `dev` extra rather than in the runtime dependencies, so the shipped tool cannot compute its own significance tests |

## Closed

Nothing yet.

---

## The two workarounds, described exactly

Both are labelled in every result file they produce, because a workaround that is
invisible in the output is indistinguishable from a capability.

### The clustered null is built here

`evaluate/triage_bridge.py` builds the paired sign-flip null at the template
level and hands it to that package's `permutation_p_value`. The estimator and the
correction stay on the far side of the boundary; the resampling scheme has ended
<!-- traceability: a specification section number, not a measurement -->
up on this side, where spec section 0.5 says it should not be.

This is the case the P5 task file called out in advance: where the specification
says clustering is non-negotiable, the absence of it in the dependency is a filed
task **plus** a clearly labelled interim analysis that resamples at the template
level before anything is passed to the harness. It is explicitly not a silent
degradation to unclustered resampling, which would have made every comparison
look more significant than it is, and which was the one outcome ruled out before
the phase began.

The manifest of every analysis records it, in `notes` and in the
`harness.not_used_for` block of `analysis.json`.

### A truthful mode string that the harness cannot label

`ComparisonResult.mode` is a plain `str` with no validation, so the bridge writes
`template_clustered_paired`, which is what ran. Two of that dataclass's derived
members, `mode_label` and `to_dict`, look the value up in a table holding the two
training modes and raise `KeyError` on anything else, so the bridge calls neither
and serialises what it needs itself. Writing `seed_replicate` instead would make
both members work and would be a false statement about which test was run.

This one is deliberately not filed on its own. It is a consequence of the same
modelling assumption as [#2](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/2),
and if a paired clustered mode lands there it will bring its own label with it.

---

## What did not need a task, and is worth saying

Two things were expected to be friction and were not.

**Categorical outcomes.** The anticipated task in this ledger, written before P5
began, was categorical-outcome support in the permutation machinery. It turned
out not to be needed, because `permutation_p_value` never sees an outcome. It
sees an observed effect and a null distribution, both floats. The categorical
part of this project's problem lives entirely in the statistic, and the statistic
is the caller's. The anticipation was aimed one layer too low.

**Benjamini Hochberg.** It needed nothing at all. It is a pure function over a
list of p values, it is checked in that repository against the worked example
from the original 1995 paper, and it did the right thing here on the first call.

Both are results, and the second is the more interesting one: the piece of that
package furthest from the domain it was extracted from is the piece that
transferred without a scratch.

---

## Status at P7

Reviewed on 2026-08-27, before the reports were compiled and before the version
was bumped. **Nothing has closed.** All five issues are open and the publication
task is open, and each was checked rather than assumed.

| Task | Issue | Status at P7 | Effect on this release |
|---|---|---|---|
| Publish `ml-experiment-triage` to a package index | [#5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | open | **Blocking.** The dependency is a git ref, so `v1.0.0` may not be tagged |
| Ingestion of a cross-sectional run log | [#1](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/1) | open | none; the bridge reads its own JSONL |
| Paired permutation with clustered resampling | [#2](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/2) | open | none; the null is built here and labelled in every result file |
| An absolute practical-effect threshold | [#3](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/3) | open | none; applied here, with the harness running alongside as a cross check |
| `classify()` reorders its output | [#4](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/4) | open | none; the bridge rejoins on object identity |
| Ship `py.typed` | [#5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | open | the mypy override stands, and the bridge is the one module whose external calls are unchecked |
| Split the ingestion and report dependencies into extras | [#5](https://github.com/Olajide-Badejo/ML-Experiment-Triage/issues/5) | open | the dependency stays in the `dev` extra, so the shipped tool cannot compute its own significance tests |

**Issue 3 still produced no verdict disagreement.** The relative gate and the
absolute one agree on every comparison in the P6 analysis:
`harness_cross_check.disagreements` is empty. That is not a reason to withdraw
the issue. A gap that happens not to bite on one dataset is still a gap, and the
dataset it would bite on is any slice with a small baseline, which is most of
what a wider benchmark would add.

### The one that blocks the release, stated plainly

The build specification forbids tagging `v1.0.0` here while any dependency is a
git ref rather than a released version. That rule was written on the first day of
this project, recorded in ADR 0001 on the day the obstacle was discovered, and it
is now the only thing standing between this repository and its first stable tag.

**The version is bumped to 1.0.0 in code and in the changelog and the tag is not
applied.** The rule holds when holding it is the expensive option, which is the
only circumstance in which a rule tells anybody anything.

The cheap way out is still available and is still refused: vendoring the three
functions this project uses would remove the blocker, and it would delete the
evidence the boundary exists to produce. See
[`adr/0004-triage-stays-external.md`](adr/0004-triage-stays-external.md).

## The cross-link, added at P7

The other side of the link is in place: that repository's README carries a
**Used by** section pointing here with a one-line description of what this
project uses it for, and a note about the friction the boundary exposed with a
link back to this ledger.

Without it the second-consumer claim is invisible to a reader who lands on either
repository alone, and an invisible claim is an unfalsifiable one.

## The gate, waived at the tag

The rule above was written to make the git-ref pin expensive, and it did its job:
the cost surfaced, was recorded, and was put to the project owner as a decision
rather than being quietly absorbed. The owner directed that v1.0.0 be tagged with
the pin still in place, on the grounds that publishing the harness to an index is
work that will not happen for a while and a stable tag is needed now.

So the deviation is recorded here, in the ledger that exists for exactly this:
**v1.0.0 is tagged while `ml-experiment-triage` is consumed from its git tag
rather than from a package index.** The publication task stays open below and is
the first item of post-1.0 housekeeping. The dependency sits in the `dev` extra,
so the shipped wheel is unaffected; what is affected is the reproducibility
guarantee of the evaluation toolchain, which now rests on a git tag rather than
on an immutable index release.
