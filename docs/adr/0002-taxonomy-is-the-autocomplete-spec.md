# ADR 0002: the taxonomy is the WHATWG autofill token set

Date: 2026-08-27
Status: accepted
Phase: P1

**Recorded at P7.** The decision itself was made and implemented at P1, when
`src/autofill_audit/taxonomy.py` was written and frozen and `docs/taxonomy.md`
was published beside it. The ADR was missed at the time and is written here from
the recorded evidence: the taxonomy module and its group partition, the extras
and their justifications in `docs/taxonomy.md`, the reachability clauses in
`scripts/check_reachability.py`, and the P1 entry in
[`../ENGINEERING_LOG.md`](../ENGINEERING_LOG.md). Nothing in it is reconstructed
from memory, and an ADR is supposed to be written when the decision is made
rather than at P7, so the lateness is the defect and this note is the record of
it.

## Context

The tool's output is an instruction to add a specific attribute value to a
specific control. That output has to name a value some browser will actually act
on, which means the label space has to be tied to something outside this
repository.

Two designs were available.

**A bespoke ontology.** Invent the categories that suit the corpus, the rules and
the model, and map them onto the specification's tokens when rendering a finding.

**The specification's token set itself**, plus a small enumerated set of extras
for outcomes the token set has no word for.

Spec sections 5.2 and 7 name the second, and the reason is worth writing out
because it is not only about correctness.

## Decision

**The ground-truth label space is the WHATWG HTML autofill field-name token set,
plus exactly five enumerated extras, defined in one module that everything else
imports from.**

Reference: the WHATWG HTML Living Standard, autofill section, retrieved
2026-08-25 and recorded with its status in
[`../references.md`](../references.md).

### The five extras, each earning its place by naming something a report has to be able to say

| Extra | Why the token set cannot say it |
|---|---|
| `NOT_AUTOFILLABLE` | A real control with no autofill meaning at all: a search box, a consent checkbox, a quantity stepper. Without this label the only available answer is `UNKNOWN`, which reads as *the tool could not tell* when the truth is *there is nothing to tell*. |
| `UNKNOWN` | The evidence genuinely does not decide. This is an answer rather than the absence of one, and law 1 requires it to exist so that a tie has somewhere to go. |
| `COMPOSITE_UNSPLIT` | One input holding what the specification models as several fields. The archetype is a single expiry box accepting month and year together. |
| `CC_EXP_SPLIT_MONTH` | Half of a split expiry pair. Individually meaningless; jointly a `cc-exp`. |
| `CC_EXP_SPLIT_YEAR` | The other half. |

The set is enumerated rather than admitted by a rule. A category that can be
added by a rule grows until the label space is nobody's specification, which
destroys the property this decision exists to buy.

### The growth rule, and why it is a script

Law 2 makes the boundary enforceable. A label may exist only if it is (a) a
specification token or one of the five extras, (b) emitted by at least one corpus
answer key, (c) reachable by at least one rule or present in the model's training
distribution, and (d) asserted by at least one test.

`scripts/check_reachability.py` enforces every clause it can currently check and
reads the taxonomy from the one source file, so the check cannot drift from the
code. Clauses moved out of its pending list and into its active set in the same
commit that made each enforceable, which is the only way a pending list stays
honest.

Two strengthenings beyond what law 2 requires are recorded here because they have
sharp edges:

- The check scans `src/` and `scripts/` for label strings written outside the
  taxonomy module, which is ground rule 6 made mechanical. The scan is limited to
  tokens that cannot be confused with ordinary prose, meaning the hyphenated
  specification tokens and the uppercase extras. `name`, `email`, `tel` and `url`
  are excluded, because a check that fires on the word `name` in a comment is a
  check somebody turns off within a week.
- A training floor clause was added at P5R: every label a model can predict must
  appear in the train partition with at least twenty rows. Three labels were
  found sitting at zero, which means the model had been asked about classes it
  had never once seen. The constant is arithmetic rather than taste and the
  derivation is in the P5R engineering log entry.

## Consequences

**The fix is a formatting of the prediction rather than a translation of it.** A
control classified as `postal-code` produces the advice `add
autocomplete="postal-code"`. There is no second, undertested mapping layer in
between, and therefore no class of bug in which the classifier is right and the
advice is wrong.

**The evaluation means something outside this repository.** Measuring a
classifier against categories the same project invented measures internal
consistency. Measuring it against the token set browsers implement measures the
thing the tool claims to do.

**The class distribution is not ours to balance.** The token set contains labels
that are rare on real forms and rare in any corpus that models real forms. Several
labels are carried by one template in one position, and macro-F1 weights them
equally with the labels on every form. That makes the label-weighted average
noisier than the field-weighted one and it is one of the two reasons both are
always reported.

**Adding a label is a specification change, not a convenience.** If the token set
grows, this project follows it. If a category is wanted that the token set does
not have, it becomes an enumerated extra with a written justification in
`docs/taxonomy.md`, or it does not exist.

**A rule can be in the table and be unreachable.** The Japanese postal mark is
named by spec section 10.1 among the strings `postal-code` should match, and it
cannot fire, because normalisation treats a lone symbol character as a delimiter.
The rule stays in the table with a comment saying so and a test asserting both
halves. Making it reachable changes what counts as a token character, which
changes every golden snapshot, so it is a deliberate change with a cost rather
than a quiet fix.
