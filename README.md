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

`v0.1.0`. The tool works and is useful, and there is no machine learning in it
yet. The extractor, the rule baseline, the audit engine, the three report
renderers, and the exit-code contract are all here; the classifier ladder climbs
from P4 onward and buys accuracy and evidence rather than usefulness.

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

Point it at a page. It exits 1 when something at or above the failure threshold
is found, so it drops straight into a pipeline.

```bash
autofill-audit audit https://example.com/checkout
autofill-audit audit ./checkout.html --format json --out report.json
autofill-audit audit ./checkout.html --format html --out report.html --fail-on warning
```

### A worked example

This is real output, from
[`tests/fixtures/checkout_hostile.html`](tests/fixtures/checkout_hostile.html),
a checkout authored in this repository to get things wrong in the ways real
checkouts get things wrong. Nothing here is edited except for trimming the
middle of the table.

```console
$ autofill-audit audit tests/fixtures/checkout_hostile.html
autofill-audit  file:///.../tests/fixtures/checkout_hostile.html

critical (6)

 control          finding
 ─────────────────────────────────────────────────────────────────────────────
 #ck-email        MISSING_AUTOCOMPLETE
                  add autocomplete="email" to #ck-email
                  evidence: declaration:absent, label:email-words [rule tier HIGH]
 #ck-postcode     OFF_SPEC_TOKEN
                  autocomplete="zipcode" is not a valid autofill token;
                  use "postal-code"
                  evidence: declaration:off-spec, label:postcode-words [rule tier HIGH]
 #ck-holder       WRONG_AUTOCOMPLETE
                  #ck-holder declares autocomplete="name" but looks like cc-name;
                  change to autocomplete="cc-name"
                  evidence: declaration:token-mismatch, label:cardholder-words [rule tier HIGH]

warning (8)

 control          finding
 ─────────────────────────────────────────────────────────────────────────────
 #input7          PLACEHOLDER_AS_LABEL
                  #input7 uses a placeholder as its label; add a real <label>
                  evidence: structure:placeholder-is-the-only-label [structural]
 #ck-mm           SPLIT_FIELD
                  #ck-mm is one half of a split expiry; set
                  autocomplete="cc-exp-month" and "cc-exp-year" on the pair
                  evidence: structure:split-expiry-group [structural]
 frame[#hosted-pan] UNDETECTABLE_FIELD
                  the control is inside a cross-origin frame, which is how hosted
                  payment fields are built on purpose; this is not necessarily a
                  defect. Autofill still works inside the frame, and the frame's
                  own document is where its autocomplete attributes belong. Audit
                  that document separately
                  evidence: structure:undetectable [structural]

$ echo $?
1
```

Three things in that output are the whole design.

**Every finding names its evidence.** `label:email-words` says which vocabulary
matched and which stream it matched in. A finding you cannot argue with is a
finding you cannot check, so there are none.

**The confidence is a tier, not a percentage.** The rule baseline is a table of
regular expressions. It has no probabilities, so it does not print any. Turning a
regex table's output into a percentage would assert a frequency nobody has
measured, which this project's third law forbids.

**A correct field is met with silence.** The card-number input on that page is
correctly declared and does not appear in the report at all. On a page where
every field is correct the whole report is one line saying so, and that property
is a test over the entire correct-markup slice of the corpus.

### The findings, in brief

| Severity | Codes |
|---|---|
| `critical` | `MISSING_AUTOCOMPLETE`, `WRONG_AUTOCOMPLETE`, `OFF_SPEC_TOKEN` |
| `warning` | `AUTOCOMPLETE_OFF`, `UNLABELED_FIELD`, `PLACEHOLDER_AS_LABEL`, `SPLIT_FIELD`, `COMPOSITE_FIELD`, `UNDETECTABLE_FIELD` |
| `info` | `GENERIC_IDENTIFIER`, `WRONG_INPUT_TYPE`, `MISSING_NAME_ATTR`, `EXTRACTION_INCOMPLETE` |
| `note` | `LOW_CONFIDENCE` |

Each one, with its trigger, its exact fix text, and a before-and-after example,
is in [`docs/findings.md`](docs/findings.md), along with the exit-code contract
and the `autofill-audit.toml` format.

## Roadmap

The build order is deliberate and the reason is worth stating: **the tool becomes
useful before any machine learning exists.**

| Phase | What lands |
|---|---|
| P0 | Repository, packaging, taxonomy, the six CI gates, the toolchain record |
| P1 | The seeded corpus generator, locale profiles, answer keys, the split policy |
| P2 | The Playwright extractor: DOM walk, frames, shadow roots, signal collection |
| P3 | The rule baseline, the audit engine, three renderers, the CLI. First usable release |
| P4 | The n-gram classifier, calibration, ONNX export, the model card |
| P5 | Metrics, run logs, statistical significance through the external harness |
| P6 | The optional local language model comparison and the headline benchmark |
| P7 | The full documentation set and the compiled reports. First stable release |

P3 is the milestone that matters to somebody who just wants their checkout page
fixed, and it has shipped as `v0.1.0`. Everything after it buys accuracy and
evidence rather than usefulness, and a project that shipped the model first and
the product last would have no way to tell whether the model was solving a
problem anybody has.

## Boundaries

These are deliberate boundaries, not missing features, and each one is a decision rather than an omission.

- **No crawling.** One page per invocation, plus the frames that page loads. There is no sitemap walker, no depth flag, and no queue.
- **No filling.** This is an auditor. It reads the DOM and reports. It never types into a field, never submits, and holds no profile of values to fill with.
- **No markup rewriting.** Findings carry a fix as text. There is no mode that edits your HTML, because rewriting a production template from a classifier's output is exactly the failure this project's first law exists to prevent.
- **The absent flags say so.** `--crawl`, `--depth`, `--fill`, `--fix`, and `--write` are each answered with the boundary they name and the reason for it, rather than with "no such option". Somebody will try each of them, and an unknown-option error reads like an oversight instead of a decision.
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
