# ADR 0003: the classifier ladder is built in a fixed order

Date: 2026-08-27
Status: accepted
Phase: P3

**Recorded at P7.** The decision was made and acted on at P3, when the rule
baseline shipped as `v0.1.0` with no machine learning in it, and it constrained
every phase after that. The ADR was missed at the time and is written here from
the recorded evidence: the phase order and its tags in
[`../../CHANGELOG.md`](../../CHANGELOG.md), the P3, P4, P5 and P6 entries in
[`../ENGINEERING_LOG.md`](../ENGINEERING_LOG.md), the per-engine threshold blocks
in `src/autofill_audit/audit/thresholds.json`, and the committed result files the
ordering made possible. An ADR is supposed to be written when the decision is
made, and the lateness is recorded rather than hidden.

## Context

Three classifiers were planned: a rule table, an n-gram logistic regression, and
a language model, with a small transformer as a conditional fourth. The order in
which they are built is not a scheduling question. It decides what each
measurement is capable of meaning.

The tempting order is the interesting one first. Build the language model, see
what it can do, and add a baseline afterwards if a reviewer asks for one.

## Decision

**The ladder is fixed in build order and is not to be reordered: rules, then
n-gram logistic regression, then the language model comparison, then, only if the
measured ceiling justifies it, a small transformer.**

**P3, the rule baseline, is the practicality milestone.** The tool is genuinely
useful to a web developer at the end of it, with zero machine learning in it, and
if the project stopped there it would still have shipped something worth
installing. Everything from P4 onward buys accuracy and evidence rather than
usefulness.

### Why rules first

A rule table is a table of regular expressions with a tier and a signal name on
every row. It has no probabilities and does not pretend to.

It is also the version of the tool that solves the user's problem. Shipping it
first forces the project to answer, before any model exists, whether the model is
solving a problem anybody has. A project that ships the model first has no
baseline to answer that with, and every subsequent measurement is a comparison
against nothing.

### Why an n-gram logistic regression before a transformer

Three reasons, in the order they matter.

1. **It fits in a wheel.** The exported model plus its vocabulary and calibration
   installs without comment, and inference needs `numpy` and `onnxruntime` and
   nothing else. The build specification pins CLI-path inference to the CPU
   execution provider for the same reason: a tool that requires CUDA to audit a
   form is a tool nobody installs.
2. **It is inspectable.** A linear model's weights name the character and word
   n-grams behind a prediction, which is exactly what law 1 requires a finding to
   carry. That property is not incidental to the design; it is why the rung is at
   that height.
3. **It sets a floor a bigger model has to beat.** Without it, any transformer
   result is a comparison against a rule table alone, and the interesting
   question, whether the extra capacity buys anything on a task whose whole input
   is a short list of attribute strings, never gets asked.

### Why the transformer is conditional

Spec section 10.7 makes it ship only if it beats a pre-stated metric by a
pre-stated margin within a pre-stated latency budget. If it does not, the
deliverable is the paragraph explaining that it did not, with the numbers, and
that is a successful phase rather than a failed one.

## Consequences

**The ordering produced the project's headline result and it could not have
produced it in any other order.** The measured answer is that the rule table
leads the label-weighted average, the n-gram model leads the field-weighted one,
and the language model came third on both. A project that had built the language
model first would have had nothing to compare it against and would have reported
that it works.

**Two engines were shipped before either had been measured against the other.**
That is the cost of the ordering and it showed up at P5: P4 measured the model on
the development split and reported what it saw, honestly, and never measured the
rule baseline on the same rows, because P4 had no evaluation runner. The two were
first put side by side at P5, which is what an evaluation phase is for, and the
result was that the model did not win anywhere. That is a P5 result rather than a
P4 defect, and the sequencing is why.

**Each rung's confidence lives on its own scale, so thresholds are per engine.**
The derived n-gram boundary sits well above the rule engine's confident band. One
shared pair of thresholds would have moved every rule-engine finding on every
page as a side effect of training a model. `thresholds.json` therefore carries a
block per engine, `load_thresholds` takes an engine name, and an engine with no
block raises rather than inheriting one. That was designed to bite when the
language model arrived without a block, and it did, which is how the zero and
zero decision came to be made deliberately and in advance.

**The rungs are not interchangeable at runtime and the CLI says so.**
`--engine auto` prefers the model when one loads and falls back to the rule
baseline with one printed line when none does. That is documented behaviour
rather than a silent degradation, and it is the reason a published wheel with no
model still audits a page correctly.

**The fourth rung is absent, in words, in every table.** Spec section 13.4's grid
carries a `bert-onnx-int8` row reading *absent* rather than blank, because a
blank cell in a comparison table reads as a measurement of zero.
