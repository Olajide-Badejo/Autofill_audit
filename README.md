# autofill-audit

Audit HTML forms for browser autofill readiness. Every finding names its evidence, its confidence, and its one-line fix.

## The problem

A browser will autofill a form field only if the markup gives it enough to recognise the field. When it cannot, the user types their address by hand, on a phone, at the last step of a checkout. That is not a cosmetic defect. It is the point in the funnel where people give up.

The web platform already says how to avoid this. The [WHATWG HTML autofill section](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#autofill) defines a token set for the `autocomplete` attribute, and the [Chrome team's form guidance](https://web.dev/learn/forms/) explains what browsers do with it. The hard part is not knowing the rule. The hard part is finding, on a page you did not write, which of sixty controls are broken and what exactly to add to each one.

That is what this tool does.

## What it does

Point it at a URL or a local HTML file. It loads the page in a real browser, walks the DOM including same-origin frames and open shadow roots, collects the signals a browser's own heuristics would use, classifies each control against the specification's token set, and reports the controls that will not autofill together with the attribute to add.

Because the label space *is* the specification's token set, the fix is a formatting of the prediction rather than a translation of it. A control classified as `postal-code` produces the advice `add autocomplete="postal-code"`, and there is no second, undertested mapping in between.

## Status

This repository is at phase P0: foundations. The packaging, the taxonomy, the CI gates, and the toolchain record are in place. The extractor arrives at P2 and the audit engine, the rule baseline, and the three report renderers arrive at P3, which is the first release a web developer can usefully install.

Until then `autofill-audit audit` refuses with a message saying so, rather than printing an empty report that would read like a clean bill of health.

## Install

```bash
pipx install autofill-audit
playwright install chromium
```

From a checkout:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,llm]"
playwright install chromium --with-deps
```

## Usage

```console
$ autofill-audit version
autofill-audit 0.0.1
```

The audit command, its `--engine`, `--format`, `--out`, and `--fail-on` flags, the finding catalogue, and the exit-code contract land at P3, and a worked before-and-after example goes here when there is real output to paste.

## Boundaries

These are deliberate boundaries, not missing features, and each one is a decision rather than an omission.

- **No crawling.** One page per invocation, plus the frames that page loads. There is no sitemap walker, no depth flag, and no queue.
- **No filling.** This is an auditor. It reads the DOM and reports. It never types into a field, never submits, and holds no profile of values to fill with.
- **No markup rewriting.** Findings carry a fix as text. There is no mode that edits your HTML, because rewriting a production template from a classifier's output is exactly the failure this project's first law exists to prevent.
- **No scraped training data.** Nothing in this repository fetches HTML from a live site and keeps it. The corpus is generated.
- **No personal data.** Test fixtures use self-evidently invented names and addresses and the officially published test card numbers. No real name, address, phone number, email, or card number is present, including the author's own.
- **HTML forms only.** Native mobile forms, PDF forms, and canvas-rendered widgets are out of scope. A canvas is reported as undetectable rather than guessed at.

## On accuracy

**This project publishes no accuracy figures yet, because none have been measured.** There is no placeholder, no rounded guess, and no number carried over from a design document. When the evaluation phase produces result files, every figure quoted anywhere in this repository will link to the committed file it came from, and a CI job checks that mechanically.

The same rule applies to estimates. Anything estimated rather than measured is labeled as an estimate where it is displayed.

## The research layer

Alongside the tool there is an honest evaluation: a seeded synthetic corpus with answer keys, a ladder of classifiers from a rule table to an n-gram model to a local large language model, and statistical significance decided by an external harness.

That harness is [ML-Experiment-Triage](https://github.com/Olajide-Badejo/ML-Experiment-Triage), a separate, independently released package, and it stays separate on purpose. A piece of infrastructure with exactly one consumer has not been shown to be infrastructure; it has been shown to be part of that one program. This project is its second consumer, across a real package boundary, and the friction that boundary exposes is recorded in [`docs/cross-repo-tasks.md`](docs/cross-repo-tasks.md) rather than smoothed away by vendoring the code.

The full write-up, including the headline comparison and whatever it turned out to show, is published at P7.

## Documentation

- [`docs/environment.md`](docs/environment.md): the resolved toolchain and the machine it was resolved on.
- [`docs/adr/`](docs/adr/): architecture decision records, written when the decision is made.
- [`docs/ENGINEERING_LOG.md`](docs/ENGINEERING_LOG.md): dated, append-only, including what went wrong.
- [`docs/ci-proof.md`](docs/ci-proof.md): every CI job observed failing, with run links, because a gate that has only ever been green is indistinguishable from a gate that always returns green.
- [`docs/references.md`](docs/references.md): sources, with retrieval dates.
- [`CHANGELOG.md`](CHANGELOG.md): keepachangelog format.

## License

MIT. See [`LICENSE`](LICENSE).
