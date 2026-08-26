# Model card: the n-gram autofill label classifier

This card documents the model committed under `models/`. It lands in the same
commit as the model, which is ground rule 8 and is the reason the card cannot
drift from the artefact it describes.

Every number below is quoted from a committed file rather than typed. The two
files are `models/dev_metrics.json` and `models/train_manifest.json`, both
written by the training run that produced the model, and both readable without
running anything. Where a number appears in this document it appears inside a
fenced block that names the file it came from.

> **The model is trained on synthetic data and its real-world accuracy is
> unmeasured until a real-world evaluation exists.** Everything reported here is
> measured on a generated corpus of this project's own forms. It says how well
> the model learned that corpus. It does not say how well it will read the next
> checkout page on the open web, and no number in this repository does.

---

## 1. What it is, and what it is for

A multinomial logistic regression over character and word n-grams of a form
control's text, plus its intrinsic attributes, its option-list shape, and its
position (spec section 10.2). It reads a `FieldDescriptor` and returns one
taxonomy label with a calibrated probability.

**Intended use.** Inside `autofill-audit`, as the classifier behind
`--engine ngram` and as the engine `--engine auto` prefers, to decide what a form
control is for so that the audit engine can tell a developer which
`autocomplete` attribute is missing or wrong.

**Out-of-scope use.** All of these are out of scope and the model will do them
badly:

- **Filling a form.** This is an auditor. Nothing here types into a field, and a
  form-filling agent is a separate project on purpose, which is one of the
  boundaries `spec section 0.4` draws.
- **Reading a page it was not shown.** The model sees a descriptor, never the
  DOM, never a screenshot, and never the declared `autocomplete` token, which is
  deliberately withheld so that a classifier cannot agree with the page by
  construction.
- **Deciding anything on its own.** Its output is a label and a probability. The
  decision to report a finding is made by the audit engine against thresholds
  derived separately, and below the high threshold a disagreement with a
  declaration produces no finding at all.
- **A general "what is this text about" classifier.** The feature space is form
  vocabulary in six locales. It has no opinion about anything else.
- **Any use where a wrong answer is expensive.** A false accusation costs a
  developer an afternoon here, which is bad enough to justify a high precision
  target, and is the ceiling of what this model should ever be trusted with.

---

## 2. The training data

Generated, synthetic, and reproducible from its seed. No real name, address,
telephone number, email, or card number is in this repository, including the
author's own (ground rule 10). Card fields use the officially published test
numbers.

```
results: models/train_manifest.json
seed                     20260825
corpus manifest sha256   15c3136f75d2d9c6807dbc70a28ab507bca1c784df53c134650e4f9898e6e035
split file sha256        c4c797ee27cec1162bc57ca3c53dc2a2392899199cbbe390e2674daba38a0ab8
form counts              train 500, dev 120, test 240, excluded 100
```

```
results: models/dev_metrics.json
train forms      500        train rows   5402
dev forms        120        dev rows     1596
excluded forms   100        classes fit    42
controls dropped as undetectable   0
controls with no answer key entry  0
```

The corpus is five form families of eight templates each, across six locales and
four markup-quality tiers (spec section 8). The tiers are the point: `clean` is
correct markup, `hostile` has its labels stripped and its identifiers obfuscated,
and the model is measured on each separately below.

**This is the second model this card has described, and none of its numbers are
comparable with the first.** The corpus was widened at P5R from five templates
per family to eight, because the test partition's template count is the
clustering unit of the significance test and five clusters could not reach the
pre-registered level at any effect size. The training partition therefore grew
from fifteen templates to twenty-five and the model was refitted from scratch.
The reason was written down before the change, in
`experiments/predictions/p5r-power-repair.md` and in `docs/ENGINEERING_LOG.md`,
and the previous model's numbers are in this file's own history rather than
beside these ones, because two models fitted on two corpora do not belong in one
table.

### 2.1 The split policy, and the held-out locale

**Templates are partitioned, not forms and not fields.** Fields within a form
share their author's naming convention, so shuffling rows and splitting them
would put fields from training templates into the test set and measure template
memorisation (spec section 8.6).

**`fr-FR` appears in no training row.** It is held out of training entirely, and
the reasoning is in `docs/adr/0005-held-out-locale.md`. Its forms in dev and test
are the unseen-locale slice, and they are the only honest test of the
cross-locale claim.

**The fourth partition is used for nothing.** `excluded` holds the
held-out-locale forms whose template landed in train. They cannot be trained on,
because the locale is held out, and they cannot be evaluated on, because their
template is a training template. The training script does not read them.

### 2.2 Per-label training counts

**Every label in the taxonomy now has training rows**, which was not true of the
previous model. Three labels then appeared in dev and in no training row at all,
so the model could not predict them under any circumstances and scored zero on
them by construction. `scripts/check_reachability.py` now enforces a minimum
directly: every label must carry at least one whole training template's worth of
rows, and the build fails otherwise. The thinnest label in the table below sits
at that minimum's double.

```
results: models/dev_metrics.json
label                   train   dev    prec     rec      f1
CC_EXP_SPLIT_MONTH         40    24    1.00    1.00    1.00
CC_EXP_SPLIT_YEAR          40    24    1.00    1.00    1.00
COMPOSITE_UNSPLIT         160    24    1.00    1.00    1.00
NOT_AUTOFILLABLE          610   228    0.99    0.96    0.98
UNKNOWN                   250    60    0.91    0.98    0.94
additional-name            60    24    0.74    0.71    0.72
address-level1            192    32    0.83    0.75    0.79
address-level2            228    44    0.67    0.68    0.67
address-line1             180    24    0.86    0.75    0.80
address-line2             180    24    0.69    0.75    0.72
address-line3              40    24    0.72    0.88    0.79
bday                       40    24    0.67    0.83    0.74
cc-csc                    200    48    0.88    0.88    0.88
cc-exp                     40     0    0.00    0.00    0.00
cc-exp-month               40    24    0.81    0.92    0.86
cc-exp-year                40    24    0.73    0.79    0.76
cc-name                   140    48    0.97    0.71    0.82
cc-number                 200    48    0.90    0.92    0.91
cc-type                    60    24    1.00    1.00    1.00
country                   180    48    0.85    0.92    0.88
country-name              100    24    0.57    0.54    0.55
current-password          100     0    0.00    0.00    0.00
email                     320    72    0.90    0.76    0.83
family-name               216    56    0.75    0.68    0.71
given-name                216    56    0.75    0.75    0.75
honorific-prefix          100    24    1.00    1.00    1.00
honorific-suffix          100    24    0.58    0.62    0.60
name                       80    24    0.56    0.42    0.48
new-password              180    48    1.00    0.94    0.97
nickname                   80    48    0.78    0.81    0.80
one-time-code             100    72    0.81    0.96    0.88
organization               60    72    0.84    0.58    0.69
postal-code               210    40    0.80    0.80    0.80
sex                        40    24    1.00    1.00    1.00
street-address             60    24    0.56    0.62    0.59
tel                        80    24    0.48    0.54    0.51
tel-country-code           80    24    1.00    0.96    0.98
tel-extension              60    24    0.92    1.00    0.96
tel-national               80    24    0.57    0.88    0.69
transaction-amount         80    24    1.00    1.00    1.00
url                        60    24    1.00    1.00    1.00
username                   80    24    1.00    1.00    1.00
```

**Two labels have training rows and no dev rows**, `cc-exp` and
`current-password`, and their zeros are a scoring artefact rather than a
statement about the model: a label with no dev examples cannot earn recall on a
split that contains none of it. The dev partition is one template per family, and
those five templates happen to carry neither a single native month expiry input
nor a sign-in password. The consequence that matters is in section 6: both are
uncalibrated, and the card names them there.

The full label space is the forty two labels of
`src/autofill_audit/taxonomy.py`, and every one of them appears above.

---

## 3. The features, and why they are inspectable

Five blocks, concatenated, all in `src/autofill_audit/classify/features.py` and
computed by one function that both the training script and the inference path
import. There is no second implementation, because train/serve feature skew is
the most common way a deployed text classifier silently degrades.

```
results: models/train_manifest.json
character n-grams (char_wb, 3 to 5)   5760 columns
word n-grams (1 to 2)                 2176 columns
categorical one-hots                    32 columns
option-shape features                    5 columns
structural features                     13 columns
total feature width                   7986 columns
```

**A fixed vocabulary, fitted on train and committed** (spec section 10.2). The
argument for hashing is that it avoids shipping a vocabulary; the argument for a
vocabulary, decisive here, is that it is inspectable. `models/vocab.json` is
readable, `models/evidence.json` carries each class's highest weighted features,
and a finding's evidence names the actual n-grams that fired rather than a hash
bucket. Hashing was the recorded fallback and was not needed.

**Option text is deliberately not in the text blocks.** Spec section 10.2 puts
the two text blocks over the descriptor's text blob and gives selects their shape
rather than their words. That is followed exactly, and the cost is real: a
hostile country select whose only evidence is its option words reaches this model
as a long list of two-letter codes, where the rule engine reaches it through its
own multilingual vocabulary.

---

## 4. Training and the sweep

Multinomial logistic regression, L2 regularised, `class_weight="balanced"`. The
class weighting matters because `NOT_AUTOFILLABLE` and `email` dominate raw
counts while `honorific-suffix` and `one-time-code` are rare, and macro-averaged
F1, the headline metric, is exactly the metric that punishes ignoring rare
classes.

The regularisation strength was chosen on the dev split by the pre-registered
grid, never on test:

```
results: models/dev_metrics.json
C = 0.25   dev macro-F1 0.7308
C = 0.5    dev macro-F1 0.7375
C = 1.0    dev macro-F1 0.7505
C = 2.0    dev macro-F1 0.7612
C = 4.0    dev macro-F1 0.7660
C = 8.0    dev macro-F1 0.7690   <- chosen
```

**The chosen value is at the edge of the grid**, which is worth saying plainly,
and it is the same edge the previous model chose. The grid was fixed before the
first run and is not being widened after seeing the result twice, because
widening a pre-registered grid because the answer landed at its edge is how a
sweep becomes a search for a number. The consequence is that this model may be
less regularised than a wider grid would have chosen, and a later phase that
revisits it re-registers first. The spread across the whole grid is a few points
of macro-F1 either way, which is smaller than the change the wider corpus
produced on its own.

---

## 5. Dev-split metrics

These are **dev numbers**. They informed the thresholds and nothing else. They
are not headline numbers, they are not in the README, and the measured comparison
against the rule baseline is a P5 result with a run manifest behind it.

```
results: models/dev_metrics.json
dev macro-F1                     0.7866
dev accuracy                     0.8421
dev macro-F1 before calibration  0.7690
abstention rate                  0.0407
accuracy when not abstaining     0.8393
```

### 5.1 Per locale

```
results: models/dev_metrics.json
locale     rows   accuracy   macro-F1
de-DE       260      0.858      0.779
en-GB       268      0.866      0.838
en-NG       260      0.892      0.837
en-US       268      0.877      0.866
fr-FR       260      0.712      0.659
ja-JP       280      0.846      0.822
```

`fr-FR` is the held-out locale and it is the worst cell in the table, by a
margin. That was the pre-registered prediction, it was true of the previous
model, and it is true of this one.

### 5.2 Per markup-quality tier

```
results: models/dev_metrics.json
tier       rows   accuracy   macro-F1
clean       369      0.954      0.930
hostile     429      0.662      0.590
mixed       429      0.830      0.771
partial     369      0.954      0.927
```

The ordering is the one the tiers were designed to produce: correct markup is
easy, obfuscated markup is hard, and the mixed tier sits between them because it
is literally made of both. The clean and partial cells being equal is worth a
sentence: a wrong `autocomplete` attribute is invisible to this model, which
never sees the declared token, so the partial tier is only as hard as its labels
and identifiers make it and those are intact.

A cell with fewer than thirty rows would report its count and no metric. None of
these cells is that small, and the rule is enforced in
`scripts/train.py::slice_report` rather than left as a caveat in prose.

### 5.3 The confusions

```
results: models/dev_metrics.json
truth                 predicted             count
email                 one-time-code             9
organization          nickname                  9
address-level1        country                   8
family-name           honorific-suffix          8
honorific-suffix      bday                      8
email                 tel-national              7
tel                   tel-national              7
NOT_AUTOFILLABLE      email                     6
additional-name       tel                       6
cc-name               cc-exp-year               6
```

**The confusion table is a different shape from the previous model's.** The
largest single confusion there ran to forty-one occurrences and was structural,
`COMPOSITE_UNSPLIT` read as `NOT_AUTOFILLABLE`; the largest here is in single
figures, and `COMPOSITE_UNSPLIT` is now scored perfectly on dev. What is left is
mostly pairs that genuinely share their evidence: `tel` against `tel-national`
differs by whether a dialling code is expected, which is a fact about the form's
intent rather than about its markup, and `organization` against `nickname` is two
free-text fields whose labels are both a proper noun.

`email` against `one-time-code` is new and is worth naming: the dev split's
verification-code fields sit beside an email address on the same page in more
than one template, and a hostile-tier code field with no label is a short numeric
input in the same neighbourhood as an email input. It is the sort of confusion
more templates create rather than remove.

---

## 6. Calibration

Fitted on the dev split, never on train and never on test. One-vs-rest with a
renormalisation step, applied by
`src/autofill_audit/classify/onnx_model.py::Calibration`, which is the same code
the tool runs, so the numbers below describe what a user experiences.

The switchover was fixed before the run: isotonic regression for a class with at
least one hundred dev positives, Platt scaling below that, and the identity for a
class with fewer than two, where fitting anything would be fitting the example.

**One class reached the isotonic switchover**, `NOT_AUTOFILLABLE`, and it is the
first one ever to. The previous model had none, and the prediction registered
before it was fitted said none would. A wider corpus put enough dev positives
behind the one label that covers every search box, quantity spinner, coupon
field, comment area and consent checkbox, and nothing else came close.

**Two classes are uncalibrated and this card names them**, `cc-exp` and
`current-password`. They have no dev positives, so their probability passes
through untouched, and a report quoting one of them is quoting an uncalibrated
softmax output. The previous model had twelve such classes; the reduction is a
consequence of the wider dev split rather than of anything done to the
calibrator.

```
results: models/dev_metrics.json
label                    dev pos        method
CC_EXP_SPLIT_MONTH            24       sigmoid
CC_EXP_SPLIT_YEAR             24       sigmoid
COMPOSITE_UNSPLIT             24       sigmoid
NOT_AUTOFILLABLE             228      isotonic
UNKNOWN                       60       sigmoid
additional-name               24       sigmoid
address-level1                32       sigmoid
address-level2                44       sigmoid
address-line1                 24       sigmoid
address-line2                 24       sigmoid
address-line3                 24       sigmoid
bday                          24       sigmoid
cc-csc                        48       sigmoid
cc-exp                         0      identity
cc-exp-month                  24       sigmoid
cc-exp-year                   24       sigmoid
cc-name                       48       sigmoid
cc-number                     48       sigmoid
cc-type                       24       sigmoid
country                       48       sigmoid
country-name                  24       sigmoid
current-password               0      identity
email                         72       sigmoid
family-name                   56       sigmoid
given-name                    56       sigmoid
honorific-prefix              24       sigmoid
honorific-suffix              24       sigmoid
name                          24       sigmoid
new-password                  48       sigmoid
nickname                      48       sigmoid
one-time-code                 72       sigmoid
organization                  72       sigmoid
postal-code                   40       sigmoid
sex                           24       sigmoid
street-address                24       sigmoid
tel                           24       sigmoid
tel-country-code              24       sigmoid
tel-extension                 24       sigmoid
tel-national                  24       sigmoid
transaction-amount            24       sigmoid
url                           24       sigmoid
username                      24       sigmoid
```

### 6.1 How well the numbers match reality

Reported, not merely performed, which is what `spec section 10.4` asks for. The
expected error below is the count-weighted mean gap between what the model said
and what happened.

```
results: models/dev_metrics.json
expected calibration error, before   0.0281
expected calibration error, after    0.0454
```

**Calibration made the expected error worse, and that is reported rather than
hidden.** The uncalibrated model of this corpus is already close to honest, and
one-vs-rest Platt scaling followed by renormalisation is not a free operation: it
refits forty-two independent sigmoids on a dev split of one template per family
and then divides by their sum, and where a class was already well behaved the
refit moves it for no gain. The previous model was badly enough calibrated that
the same procedure helped it; this one is not.

The right response to that is not to drop the calibrator, because macro-F1 rises
with it (section 5) and because the argument in spec section 10.4 is about the
confidence a finding quotes rather than about the average gap. It is to say
plainly that the number a finding quotes is a calibrated probability whose
expected gap from reality is what the block above says it is, and to keep the
high threshold where the derivation put it.

The reliability curve after calibration, over the winning class's probability:

```
results: models/dev_metrics.json
bin              count   predicted    observed
0.0 to 0.1           0
0.1 to 0.2          17       0.178       0.118
0.2 to 0.3          77       0.260       0.195
0.3 to 0.4          78       0.355       0.218
0.4 to 0.5          61       0.458       0.508
0.5 to 0.6          76       0.550       0.658
0.6 to 0.7          72       0.650       0.875
0.7 to 0.8          93       0.746       0.677
0.8 to 0.9         112       0.859       0.893
0.9 to 1.0        1010       0.975       0.993
```

Two things in that curve deserve to be said rather than left for a reader to
find. The model is still **overconfident at the bottom**: in the three lowest
occupied bins it says roughly a fifth to a third and is right less often than
that. And it is **under**confident through the middle, most visibly in the bin
just below seven tenths, where it says roughly two thirds and is right closer to
nine tenths. The first is the direction that would matter and it is the argument
for the high threshold sitting where it does rather than lower; the second costs
recall and nothing else. The top bin holds most of the mass and is close to
right, which is the bin the reported findings come from.

### 6.2 Abstention

When the winning class is `UNKNOWN` the reported confidence is zero, exactly as
the rule engine reports it, rather than the calibrated probability of the
`UNKNOWN` class. The decision procedure treats `UNKNOWN` as "the tool has nothing
to say", and a model emitting a high confidence there would reach the right
outcome by accident. The second class and its probability stay on `runner_up`.

---

## 7. The exported artefact

```
results: models/train_manifest.json
onnx opset                 26
execution provider         CPUExecutionProvider
intra-op threads           1
graph                      one LinearClassifier node, one L1 Normalizer
```

The graph holds the linear layer and nothing else. Featurisation happens in
Python on both sides of the train/serve boundary, and calibration is applied
after the session returns. The route and its evidence are in
`docs/adr/0006-onnx-export-path.md`.

**The parity gate.** The entire dev split was run through the scikit-learn
pipeline and through the ONNX session and compared row by row:

```
results: models/dev_metrics.json
rows compared                        1596
rows agreeing on argmax              1596
largest per-class probability gap    4.768e-07
tolerance                            1.0e-05
```

---

## 8. Known failure modes

Each of these is visible in the numbers above, and each is a reason not to trust
a particular answer rather than a reason not to use the model.

- **An unseen locale.** `fr-FR` is the worst cell in the per-locale table, by a
  wide margin. Character n-grams carry some of it, because French and English
  share Latin substrings, and they do not carry all of it. A locale outside the
  six in the corpus has never been measured at all.
- **Hostile markup.** The hostile tier is the worst cell in the per-tier table.
  Labels are stripped and identifiers are obfuscated there, which is exactly the
  case the tool exists for and exactly the case with the least evidence in it.
- **A label with no dev rows.** `cc-exp` and `current-password` have training
  rows and no dev examples, so they are uncalibrated and their reported
  confidence is a raw softmax output rather than a probability. The failure mode
  the previous model had, a label with no *training* rows that it could never
  predict at all, is now impossible: `check_reachability.py` fails the build on
  it.
- **The labels that share their evidence.** `name` against the split name pair,
  `street-address` against `address-level2`, and `country-name` against
  `country` are the three lowest F1 scores in the per-label table. Each is a pair
  the markup genuinely does not separate, which is why the rule table declines to
  separate some of them at all.
- **Custom widgets.** A control inside a closed shadow root or drawn on a canvas
  never reaches the model at all. The extractor reports it as undetectable and
  the engine short-circuits it, which is the honest outcome and is not a
  classification.
- **Telephone fields.** `tel` and `tel-national` differ by whether a dialling
  code is expected, which is a fact about the form's intent and is almost never
  in the markup. The pair is in the confusion table in both directions and `tel`
  carries one of the lowest F1 scores in the per-label table.

---

## 9. Reproducing this model

```
autofill-audit train --corpus corpus --split-file corpus/split.json \
    --seed 20260825 --out models
```

The training run reads only the train partition for fitting and only the dev
partition for calibration and for the sweep. It refuses to read the test
partition at all, enforced by a path check on every corpus path it resolves and
by an audit hook that raises on any other open.

```
results: models/train_manifest.json
python          3.14.4
numpy           2.5.2
onnx            1.22.0
onnxruntime     1.29.0
playwright      1.62.0
scikit-learn    1.9.0
scipy           1.18.1
skl2onnx        1.20.0
```

Training used no GPU. Inference uses no GPU and never will: a tool that requires
CUDA to audit a form is a tool nobody installs (spec section 5.4).

---

## 10. The statement that may not be softened

**The model is trained on synthetic data and its real-world accuracy is
unmeasured until a real-world evaluation exists.**

---

## 11. How this model compares against a language model

Added at P6, when the third engine arrived and the comparison of spec section
13.4 was run. The numbers are in the README and in the result files it links to;
what belongs on this card is what the comparison says about **this** model.

**This model beat a 12-billion-parameter instruction model at 4-bit
quantization** on macro-F1 and on micro-F1, on every markup-quality tier, and on
the seen-locale slice, on the test split of this corpus. The language model led it
on one slice, the held-out locale, and that difference did not survive the
correction across the comparison family.

**Three limits on reading that as a general result**, all of which favour this
model and none of which it earned:

1. **This model was fitted on this corpus's own training split.** The language
   model saw the corpus for the first time at inference. A comparison between a
   model fitted on the distribution and a model that was not is a comparison of
   two different things, and on a synthetic corpus with a generator behind it the
   fitted one has more to gain than it would on real pages.
2. **The task is close to the worst case for a language model.** The entire input
   is a short list of attribute strings and text fragments. There is no prose to
   reason over and little for world knowledge to contribute beyond what a naming
   convention already encodes.
3. **One model, one quantization, one prompt.** No fine-tuning was attempted and
   no prompt search was run. A different model or a better prompt could move it.

**What the comparison does establish for this card** is that the calibrated
confidence on this model is doing work that parameter count does not substitute
for. The language model's confidence is self-reported, which spec section 12.1
forbids from gating anything, so its threshold block is zero and it accuses
whenever it has an answer. It found more real defects than this model and was
wrong about roughly one accusation in five. This model, gated by a boundary
derived against a pre-registered precision target, accused less often and was
right far more often when it did.

That is the trade section 6 of this card exists to document, measured against a
system that has no equivalent of it.
