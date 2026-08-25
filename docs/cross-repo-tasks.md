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

## Open

| Task | Why it blocks | Status | Landed in | Constraint here |
|---|---|---|---|---|
| Publish `ml-experiment-triage` to PyPI | The package exists only as a GitHub repository. P5 may pin a pre-release from a git tag, but the release rule above forbids tagging `v1.0.0` here while a dependency is a git reference, so publication is a hard blocker on this project's first stable release. | open | not yet | none yet; the dependency is deliberately absent from `pyproject.toml` until P5 |
| Categorical-outcome support in the permutation machinery | That package's permutation tests were designed against continuous outcomes. This project's headline metric is per-label accuracy over a categorical outcome, and clustering must be by corpus template rather than by row. Whether the public API already covers this is unknown until P5 tries it. | anticipated, not yet filed | not yet | none yet |

## Closed

Nothing yet.

## Notes

The second row is written as an expectation rather than a defect on purpose. It
is the specific friction the package boundary is expected to expose, and naming
it in advance means that if P5 finds the public API sufficient, that is a result
worth reporting too, rather than an absence nobody notices.

At P7 the other side of the link is added: that repository's README gains a
"used by" entry pointing here with a one-line description of what this project
uses it for. Without it the second-consumer claim is invisible to a reader who
lands on either repository alone.
