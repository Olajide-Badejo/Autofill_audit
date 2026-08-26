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

`v0.3.0`. The tool works and is useful. The extractor, the rule baseline, the
audit engine, the three report renderers, and the exit-code contract have been
here since `v0.1.0`, and the classifier ladder has a second rung: an n-gram
logistic regression, calibrated on a held-out development split and exported to
ONNX, behind `--engine ngram`.

`--engine auto` prefers the model when one loads and falls back to the rule
baseline with one printed line when none does, which is the documented behaviour
rather than a failure. A published wheel does not currently carry a model, so a
`pipx` install runs the rule baseline until you train one or point
`AUTOFILL_AUDIT_MODEL_DIR` at a bundle.

**The default engine is the rule baseline, and the measurements below are the
reason.** On the first test-split evaluation the n-gram model lost to the rule
table on every slice measured. That is not the result the classifier ladder was
built expecting, it is printed here anyway, and what to do about it is the
subject of the next phase rather than of a rewritten paragraph in this one.

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

Every number below links to the committed result file that produced it. A CI job
follows each link to the file, from the file to its run manifest, and from the
manifest to a commit in this repository, and fails if any step does not resolve.
Nothing here is typed by hand, rounded from memory, or carried over from a design
document, and a result produced from a modified working tree is marked as such in
its manifest and may not be cited at all.

**These are measurements on a seeded synthetic corpus, not a claim about the open
web.** The corpus is generated by this repository, five form families across six
locales and four markup-quality tiers, with whole templates assigned to the
training, development and test splits so that no test form shares an author with
a training form. How the tool behaves on real pages is unmeasured and is stated
as unmeasured.

### What a developer experiences

The finding-level numbers come first because they are what a user of the tool
actually sees: they run through the decision procedure and the thresholds rather
than reporting raw classifier accuracy.

| Engine | `MISSING_AUTOCOMPLETE` precision | Accusations | Recall | Fields needing one | Result file |
|---|---|---|---|---|---|
| `rules` | 1.0000 | 206 | 0.5954 | 346 | [metrics.json](experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json) |
| `ngram` | 1.0000 | 32 | 0.0925 | 346 | [metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json) |

Both engines were right about every field they accused, and the rule baseline
found more than six times as many of them.

The other accusation code, `WRONG_AUTOCOMPLETE`, is not reported as a rate for
either engine. It had eleven eligible fields on the test split, below the
thirty-field reporting minimum this project fixed before it had any numbers, so
the counts are in the result files and the rates are withheld. A precision
computed over ten accusations and a precision computed over a thousand are the
same number and are not the same claim.

**Read the two rows as a comparison of two policies, not two classifiers.** The
n-gram engine speaks only when a calibrated probability clears a threshold
<!-- traceability: the target is a pre-registered policy constant in thresholds.json, not a measurement -->
derived against a precision target of 0.98; the rule baseline speaks when a
regular expression matches at a tier that a documented mapping calls confident.
They are answering the same question under different rules about when to answer.

### The classifier comparison

| Engine | macro-F1 | micro-F1 | macro-F1, unseen locale | Result file |
|---|---|---|---|---|
| `rules` | 0.7785 | 0.7744 | 0.7193 | [metrics.json](experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json) |
| `ngram` | 0.4151 | 0.7041 | 0.4057 | [metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json) |

The unseen-locale column is the multilingual claim's actual test: French forms
whose templates are also unseen, so the model is not being asked about a naming
convention it has met before.

Abstention explains most of the gap between the two averages.

| Engine | Answers `UNKNOWN` on | Accuracy on the rest | Result file |
|---|---|---|---|
| `rules` | 0.2676 | 0.9773 | [metrics.json](experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json) |
| `ngram` | 0.0508 | 0.6996 | [metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json) |

A classifier that abstains often and is right when it commits is a legitimate
design, and on this corpus it is the better one.

### Latency, in the context that decides whether it matters

| Engine | p50 | p95 | p99 | Result file |
|---|---|---|---|---|
| `rules` | 36.1 | 135.1 | 181.3 | [metrics.json](experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json) |
| `ngram` | 173.1 | 327.3 | 515.7 | [metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json) |

Microseconds per field, on a CPU, with the ONNX session warmed and its threads
pinned. Both are comfortably inside a millisecond, and both are irrelevant to
what anybody actually waits for.

| Engine | Share of wall time spent loading and extracting the page | Result file |
|---|---|---|
| `rules` | 0.98 | [metrics.json](experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json) |
| `ngram` | 0.98 | [metrics.json](experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json) |

The browser is the cost. Celebrating the difference between the two latency
columns would be celebrating a rounding error on a page load.

### Is the difference significant

No, and the reason is a property of the corpus rather than of the engines.

Fields inside one form template share an author, so the significance test
resamples whole templates rather than individual fields. The test split holds
five templates, which gives a paired sign-flip space of thirty-two arrangements.
The smallest two-sided p value that design can produce is 0.0625 ([analysis.json](experiments/results/analysis/2026-08-26T02-53-59Z_analysis_336175f/analysis.json)),
<!-- traceability: the level is a pre-registered policy constant, fixed before the runs in experiments/predictions/p5-statistical-policy.md -->
which is above the false-discovery level of 0.05 that was fixed before the runs.
Every one of the eleven comparisons is therefore reported as inconclusive: the
design cannot reach that level, whatever the effect
([analysis.json](experiments/results/analysis/2026-08-26T02-53-59Z_analysis_336175f/analysis.json)).

Seven of the eleven sit exactly at that floor, meaning the observed difference
was more extreme than all thirty-one other arrangements the design permits
([analysis.json](experiments/results/analysis/2026-08-26T02-53-59Z_analysis_336175f/analysis.json)).
That is the strongest evidence this corpus can produce and it is still not
significance. Saying "no significant difference" here would be a different and
false claim; the difference is large and this split cannot certify it. Generating
more templates per family is what fixes it, and that changes the corpus and
therefore the model, so it is the next phase's work and not a footnote in this
one.

The same rule applies to estimates. Anything estimated rather than measured is
labeled as an estimate where it is displayed.

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
