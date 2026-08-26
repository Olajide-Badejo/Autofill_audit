---
predicts:
  - src/autofill_audit/audit/thresholds.json
  - experiments/results/test/*p6*
  - experiments/results/analysis/*p6*
---

# Pre-registered: the headline benchmark of spec section 13.4, and what it will show

Date: 2026-08-26. Phase P6, branch `phase/p6-llm-headline`.

This file is committed **before** the language-model engine classifies a single
field of the test split, and before the `llm` block is written into
`src/autofill_audit/audit/thresholds.json`.
`scripts/check_prediction_ancestry.py` verifies that mechanically, from the front
matter above, at the gate and in CI.

Every number quoted below as an observation is cited to a committed result file
and every number quoted as an expectation is marked as one. Nothing here has
been seen on a language-model run of any split. The predictions are written to
be **contradictable**: each names the quantity, the direction, and the margin
that would falsify it, because a prediction that cannot be wrong is a
description.

---

## 1. What is being decided, and what is being fixed in advance

Spec section 13.4 asks one question:

> Does a 50-kilobyte linear model that runs in microseconds on a CPU get close
> enough to a 12-billion-parameter model to be the right default for a developer
> tool?

The P5R handoff established that the question has a three-way shape rather than a
two-way one. Test split, 240 forms, 2317 classified fields, 10 templates:

| | rules | ngram |
|---|---|---|
| macro-F1 | 0.7911 | 0.7394 |
| micro-F1 | 0.7678 | 0.8226 |
| macro-F1 unseen locale | 0.7276 | 0.5637 |
| macro-F1 hostile tier | 0.4681 | 0.5409 |
| abstention rate | 0.2620 | 0.0363 |

From `experiments/results/test/2026-08-26T06-18-34Z_p5r-rules_0d900ff/metrics.json`
and `experiments/results/test/2026-08-26T06-21-03Z_p5r-ngram_0d900ff/metrics.json`.

The two averages disagree about which of the two existing engines won, and both
are correct: macro-F1 is free about abstention and micro-F1 is not. **Every table
this phase produces carries both averages and says what each weights.** A
three-engine grid that reported one of them would be picking a winner by picking
a denominator, and that decision is taken here rather than after the numbers
arrive.

### 1.1 Fixed before the runs, and not revisited afterwards

- **Model.** `mistral-nemo:12b-instruct-2407-q4_K_M` through Ollama's
  OpenAI-compatible `/v1/chat/completions`, structured output enforced with a
  JSON schema passed on the request, the label `enum` injected from
  `taxonomy.py`. A 12B-class instruction model at 4-bit quantization, which is
  what spec section 0.3 pins.
- **Decoding.** `temperature` 0 and `seed` 20260825, both recorded in the run
  manifest. Determinism is **not** claimed: the server is free to ignore either,
  and batched GPU reduction order is not stable. The report says so rather than
  implying a reproducibility the stack does not provide.
- **Batching.** One request per page where the page fits, capped at 40 fields per
  request, with an overflow page split into further requests. The cap and the
  realised distribution are recorded in the run manifest.
- **Input.** The pruned descriptor list of spec section 12.2, never raw HTML.
  Geometry, framework attributes and **the declared `autocomplete` value** are
  dropped. Dropping the declaration is what stops the clean tier from being
  readable off the page.
- **Statistical policy.** Unchanged from `p5-statistical-policy.md`: alpha 0.05,
  false discovery rate 0.05, absolute practical-effect threshold 0.02 of
  macro-F1, clustering by template, paired sign-flip permutation, exact where the
  arrangement space allows.

### 1.2 The comparison family, decided here rather than after the runs

The P5R analysis corrected across a family of eleven: macro-F1 on seven slices
plus precision and recall for two finding codes, for one engine pair.

**The P6 headline family is all three engine pairs over the same eleven
comparisons, corrected together as one family of up to thirty-three.** Not two
families of eleven, and not one family of eleven with the language model
substituted in.

Correcting inside a smaller family and calling it the family is the standard way
to manufacture a significant result, and the temptation here is specific and
foreseeable: the comparison this phase exists to make is the one against the
language model, and a family containing only that pair would be a third the size
and would produce smaller adjusted p values for exactly the comparisons the
project most wants to be able to report. So the size is fixed now, while it is
still costless to fix it.

**Consequence, stated in advance so nobody reports it as a change:** every
rules-against-ngram comparison will carry a larger adjusted p in the P6 analysis
than the same comparison carried in the P5R analysis. The underlying p values do
not move. The P5R analysis file is left exactly as it is, as the record of what
was known then.

### 1.3 The threshold block, and why it will not be derived

`load_thresholds("llm")` currently raises, and spec section 11.3's decision
procedure is engine-agnostic by confidence value: `audit/engine.py` compares
`prediction.confidence` against `tau_high` whatever produced it. So the language
model needs a block, and the block's contents are a real decision.

**Spec section 12.1 settles it: a self-reported confidence never feeds the
threshold policy of section 11.3.** Therefore the `llm` block will declare
`tau_high` and `tau_low` at **0.0**, and its `basis` string will say plainly that
the numbers are not a boundary derived on any scale, that they exist because the
decision procedure requires two floats, and that they are set so that the
self-reported number decides nothing.

The consequences are stated in advance, because two of them are unflattering and
would look like defects if they surfaced without warning:

1. **The language model gets no threshold protection.** Every committed
   prediction that has a declaration becomes an accusation. The n-gram engine's
   accusations are gated by a boundary derived on the dev split against a 0.98
   precision target; the language model's are not gated at all. A finding-level
   precision comparison between them is therefore **not** a comparison of two
   classifiers, and the sentence saying so travels with the table.
2. **`LOW_CONFIDENCE` becomes unreachable for this engine**, because `tau_high`
   fires first on every field. That is correct rather than broken: an engine
   whose confidence is not a scale cannot have a band partway along it.

The alternative, deriving a boundary on the self-reported scale against a
precision target the way P4 did for the n-gram engine, is rejected here rather
than after seeing whether it would have helped. It is the thing spec section 12.1
forbids, and the fact that it would probably raise the language model's
finding-level precision is the reason to refuse it in advance rather than a
reason to reconsider.

---

## 2. The predictions

Each is stated with the quantity, the direction, and what would falsify it. They
may all be wrong. Spec section 13.4 requires that both possible answers be
printable, so the write-up prints whichever arrives.

### P1. The language model beats the n-gram model on the hostile tier

**Prediction:** `llm` macro-F1 on the `hostile` tier exceeds `ngram`'s 0.5409 by
more than the practical threshold of 0.02, that is, it lands above 0.5609.

**Why:** the hostile tier strips identifiers and labels down to obfuscated
markup, which is where a bag of character n-grams fitted on 25 templates has
least to work with and where broad pretrained knowledge of how real checkout
pages are written should carry the most. Spec section 13.4 names this as the
plausible outcome.

**Falsified by:** a hostile-tier macro-F1 at or below 0.5609.

### P2. The language model beats the n-gram model on the unseen locale

**Prediction:** `llm` macro-F1 on the `unseen_locale` slice exceeds `ngram`'s
0.5637 by more than 0.02, that is, it lands above 0.5837.

**Why:** the held-out locale is `fr-FR`, which the n-gram model has never seen a
token of and which a multilingual pretrained model has seen a great deal of. This
is the multilingual claim's actual test and it is the slice where the two systems
differ most in what they were built from.

**Falsified by:** an unseen-locale macro-F1 at or below 0.5837.

### P3. The language model does not beat the rule table on the unseen locale

**Prediction:** `llm` macro-F1 on `unseen_locale` does **not** exceed the rule
table's 0.7276.

**Why:** the rule table abstains on roughly a quarter of its fields and is right
on 97 percent of what it commits to, and macro averaging is free about
abstention. A model that answers nearly everything pays for every wrong answer in
a rare class. This prediction is deliberately in tension with P2: both can hold,
because the rule table currently leads the n-gram model on that slice by sixteen
points.

**Falsified by:** an unseen-locale macro-F1 above 0.7276.

### P4. Latency differs by at least three orders of magnitude

**Prediction:** `llm` p95 latency per field exceeds `rules`' 134.7 microseconds
and `ngram`'s 256.6 microseconds by a factor of at least 1000, that is, it lands
above 256600 microseconds per field, batching amortisation included.

**Why:** a forward pass over a 12-billion-parameter model at 4-bit quantization
on one consumer card is milliseconds to seconds per request, and a page carries
roughly ten fields, so even one request per page leaves three orders of magnitude
between the two.

**Falsified by:** a p95 per field below 256600 microseconds.

**And the counterweight, predicted with it:** the whole-run wall time will still
be dominated by the browser rather than by the classifier for the rule and n-gram
engines, whose load-and-extract share was 0.9913 and 0.9870 on the P5R runs. For
the language model it will not be. The report states both, because a latency
difference that the user never experiences and one that the user experiences as
the whole runtime are different findings.

### P5. Schema compliance fails, but rarely

**Prediction:** the fraction of requests needing more than one attempt is
**greater than zero and below 0.05**. Structured output makes validity the
server's job, so most failures should be semantic rather than syntactic: the
model returning a selector that was not asked for, or omitting one, rather than
returning something that is not JSON.

**Why greater than zero:** a constrained decoder guarantees the shape of the
document, not that it contains one entry per requested selector with the
selectors spelled as given. Long selector strings copied through a decoder are
exactly where a model drifts.

**Falsified by:** zero retried requests, or a retry rate at or above 0.05.

**And the accounting is fixed in advance:** any field whose selector cannot be
resolved after the one parse retry and the one semantic retry is scored
`UNKNOWN`, stays in the denominator, and is counted in the results table. Spec
section 12.3 point 4 is explicit that quietly excluding a model's schema failures
is the single most common way an LLM benchmark flatters its subject, and the
count appears in the run manifest whether it is zero or not.

### P6. The practical conclusion will not depend on who wins

**Prediction:** whichever engine leads on macro-F1, the write-up's answer to spec
section 13.4's question will be that **the n-gram model remains the right default
for a developer tool**, and the reason will be latency and dependency footprint
rather than accuracy.

**Why:** a tool that ships as a `pipx install` and audits a page in a
continuous-integration job cannot require a 7.5 gigabyte model file and a GPU,
and P4's prediction is that the accuracy gap will not be large enough to make
that requirement worth it.

**Falsified by:** a measured gap large enough that the recommendation flips, and
the file records now what that would take: `llm` leading the better of the two
existing engines by more than 0.10 of macro-F1 overall **and** on the hostile
tier **and** on the unseen locale. Three slices rather than one, because a single
slice is where a lucky result lives.

This is the prediction most at risk of being confirmed for the wrong reason, and
it is stated because spec section 13.4 requires the write-up to be willing to
print the opposite. If the language model wins decisively, the honest conclusion
is that it is the better classifier and the n-gram model is the better product,
and the report will say that with the numbers behind it.

### P7. The confusion pairs, restated from the committed test-split matrices

Spec section 13.2's four predicted pairs were restated at P5R against what
actually occurred rather than against the specification's guesses. Predicted for
the language model:

- `tel-national as tel` **will** occur, because it occurred for both existing
  engines and the distinction is a convention rather than a signal on the
  control.
- `username as email` will **not** occur in either direction, because it has not
  occurred for either engine on either corpus, and because a model asked to
  distinguish them has the field's own type attribute to go on.
- The largest single confusion will be a `NOT_AUTOFILLABLE` field read as
  something autofillable, as it was for both existing engines. A language model
  told to use `NOT_AUTOFILLABLE` for search boxes, quantity inputs and consent
  checkboxes is being asked to decline, and declining is the behaviour the prompt
  has least leverage over.

**Falsified by:** the corresponding cell of the committed confusion matrix.

### P8. Abstention will sit between the two existing engines

**Prediction:** the `llm` abstention rate lands strictly between `ngram`'s 0.0363
and `rules`' 0.2620.

**Why:** the system prompt instructs the model to answer `UNKNOWN` when the
evidence is insufficient and not to guess, which is more abstention pressure than
a linear model under a fixed threshold has and less than a rule table that says
nothing at all when no rule fires.

**Falsified by:** a rate outside that interval in either direction.

---

## 3. What is not being predicted, deliberately

- **Nothing is predicted about cost**, because the local path has none. Spec
  section 12.4 requires local calls to log `null` rather than `0.0`, since zero
  is a measurement and the electricity was not free. The cloud client exists as a
  configuration swap and is never run here, so its price table is a documented
  list-price estimate with a retrieval date and no run behind it.
- **Nothing is predicted about the `bert-onnx-int8` row**, which is P8 and does
  not exist. The headline table reports it **absent**, in words, not as a blank
  cell.
- **No calibration block is predicted**, because a self-reported confidence is
  not a probability and computing an expected calibration error over it would
  produce a number whose units do not exist. The metrics document will carry
  `calibration: null` for this engine, as it already does for the rule table.

---

## 4. If the serving route changes

The model is decided and so is the fallback ladder of spec section 3.4. If the
resolved route turns out to be a smaller quantization, a smaller model, or a
CPU-offloaded one, that is recorded in `docs/adr/0007-llm-model-and-quantization.md`
with the observed VRAM headroom, **the affected rows of the headline table are
labelled with the tag and quantization that actually ran**, and the predictions
above stand as written against whatever ran. Relabelling a row is honest;
rewriting a prediction after seeing which model was available is not, and the
`amended:` line of the front matter is the only way this file may change.
