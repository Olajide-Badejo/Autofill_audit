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
corpus manifest sha256   3450c48b009b3365f87f21e4f6703540e12c80885620a8612739e0e4eafcdb6b
split file sha256        67f524a0fd4c8590b3b758d6a000083210a1195d8304706185b4e24649bfbe60
form counts              train 300, dev 120, test 120, excluded 60
```

```
results: models/dev_metrics.json
train forms      300        train rows   2889
dev forms        120        dev rows     1118
excluded forms    60        classes fit    39
controls dropped as undetectable   0
controls with no answer key entry  0
```

The corpus is five form families across six locales and four markup-quality
tiers (spec section 8). The tiers are the point: `clean` is correct markup,
`hostile` has its labels stripped and its identifiers obfuscated, and the model
is measured on each separately below.

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

Three labels appear in dev and in no training row, which is a fact about the
split rather than a defect: the split partitions templates, and no training
template happens to emit them. The model cannot predict them at all, and their
zero rows below are the honest consequence.

```
results: models/dev_metrics.json
label                   train   dev    prec     rec      f1
COMPOSITE_UNSPLIT          40    72    0.53    0.26    0.35
NOT_AUTOFILLABLE          350    84    0.64    0.87    0.74
UNKNOWN                   150    60    0.56    0.57    0.56
address-level1            112    32    0.64    0.66    0.65
address-level2            140    44    0.54    0.77    0.64
address-line1             140    24    0.45    0.62    0.53
address-line2             140    24    0.73    0.92    0.81
address-line3              40     0    0.00    0.00    0.00
cc-csc                    120    48    0.91    0.90    0.91
cc-exp                     40     0    0.00    0.00    0.00
cc-exp-month               20    24    0.65    0.62    0.64
cc-exp-year                20    24    0.61    0.46    0.52
cc-name                   100     0    0.00    0.00    0.00
cc-number                 120    48    0.98    0.96    0.97
cc-type                    20    24    1.00    1.00    1.00
country                   120    48    0.76    0.71    0.73
country-name                0    24    0.00    0.00    0.00
email                     160    72    1.00    1.00    1.00
family-name                96    56    0.88    0.75    0.81
given-name                 96    56    0.82    0.82    0.82
honorific-prefix           20    24    1.00    1.00    1.00
honorific-suffix           20    24    0.96    0.96    0.96
name                       40    24    0.88    0.88    0.88
new-password               80    24    1.00    1.00    1.00
one-time-code               0    24    0.00    0.00    0.00
organization               60    24    0.91    0.83    0.87
postal-code               125    66    0.68    0.76    0.72
street-address              0    24    0.00    0.00    0.00
tel                        60    24    0.48    0.42    0.44
tel-country-code           40    24    0.92    1.00    0.96
tel-extension              40     0    0.00    0.00    0.00
tel-national               40    24    0.31    0.54    0.39
transaction-amount         20    24    0.94    0.62    0.75
url                        40    24    0.67    0.75    0.71
username                   60     0    0.00    0.00    0.00
```

Labels with no row in that table carry no dev examples and no dev predictions.
The full label space is the forty two labels of `src/autofill_audit/taxonomy.py`.

---

## 3. The features, and why they are inspectable

Five blocks, concatenated, all in `src/autofill_audit/classify/features.py` and
computed by one function that both the training script and the inference path
import. There is no second implementation, because train/serve feature skew is
the most common way a deployed text classifier silently degrades.

```
results: models/vocab.json
character n-grams (char_wb, 3 to 5)   4905 columns
word n-grams (1 to 2)                 1701 columns
categorical one-hots                    32 columns
option-shape features                    5 columns
structural features                     13 columns
total feature width                   6656 columns
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
C = 0.25   dev macro-F1 0.4920
C = 0.5    dev macro-F1 0.5080
C = 1.0    dev macro-F1 0.5123
C = 2.0    dev macro-F1 0.5170
C = 4.0    dev macro-F1 0.5166
C = 8.0    dev macro-F1 0.5262   <- chosen
```

**The chosen value is at the edge of the grid**, which is worth saying plainly.
The grid was fixed before the run and is not being widened after seeing the
result, because widening a pre-registered grid because the answer landed at its
edge is how a sweep becomes a search for a number. The consequence is that this
model may be less regularised than a wider grid would have chosen, and a later
phase that revisits it should say so and re-register.

---

## 5. Dev-split metrics

These are **dev numbers**. They informed the thresholds and nothing else. They
are not headline numbers, they are not in the README, and the measured comparison
against the rule baseline is a P5 result with a run manifest behind it.

```
results: models/dev_metrics.json
dev macro-F1                     0.5813
dev accuracy                     0.7093
dev macro-F1 before calibration  0.5262
abstention rate                  0.0546
accuracy when not abstaining     0.7181
```

### 5.1 Per locale

```
results: models/dev_metrics.json
locale     rows   accuracy   macro-F1
de-DE       180      0.750      0.600
en-GB       188      0.739      0.621
en-NG       182      0.769      0.655
en-US       188      0.750      0.643
fr-FR       180      0.556      0.431
ja-JP       200      0.690      0.594
```

`fr-FR` is the held-out locale and it is the worst cell in the table, by a
margin. That was the pre-registered prediction and it is what happened.

### 5.2 Per markup-quality tier

```
results: models/dev_metrics.json
tier       rows   accuracy   macro-F1
clean       249      0.835      0.740
hostile     310      0.523      0.405
mixed       309      0.702      0.589
partial     250      0.824      0.707
```

A cell with fewer than thirty rows would report its count and no metric. None of
these cells is that small, and the rule is enforced in
`scripts/train.py::slice_report` rather than left as a caveat in prose.

### 5.3 The confusions

```
results: models/dev_metrics.json
truth                 predicted             count
COMPOSITE_UNSPLIT     NOT_AUTOFILLABLE         41
street-address        address-level2           14
one-time-code         COMPOSITE_UNSPLIT        13
tel                   tel-national             13
country               address-level1           12
country-name          address-level2           12
UNKNOWN               postal-code              11
address-level1        country                  11
tel-national          tel                      11
COMPOSITE_UNSPLIT     username                  7
```

Three of the four pairs predicted in advance under law 4 are here: `tel` against
`tel-national` in both directions, the address levels against `country`, and the
address family against itself. `username` against `email` is **not**, and the
reason is visible in the per-label table: `email` is the one label the model gets
exactly right, and `username` has no dev rows at all in this split.

---

## 6. Calibration

Fitted on the dev split, never on train and never on test. One-vs-rest with a
renormalisation step, applied by
`src/autofill_audit/classify/onnx_model.py::Calibration`, which is the same code
the tool runs, so the numbers below describe what a user experiences.

The switchover was fixed before the run: isotonic regression for a class with at
least one hundred dev positives, Platt scaling below that, and the identity for a
class with fewer than two, where fitting anything would be fitting the example.

**No class reached the isotonic switchover.** The dev split is one fifth of the
corpus spread across forty two labels, and the arithmetic does not leave room.
That was predicted in advance and it is what happened, and it means every
calibrated class in this model is calibrated by Platt scaling.

**Twelve classes are uncalibrated and this card names them.** They have no dev
positives, so their probability passes through untouched, and a report quoting
one of them is quoting an uncalibrated softmax output. They are:
`CC_EXP_SPLIT_MONTH`, `CC_EXP_SPLIT_YEAR`, `additional-name`, `address-line3`,
`bday`, `cc-exp`, `cc-name`, `current-password`, `nickname`, `sex`,
`tel-extension`, and `username`.

```
results: models/dev_metrics.json
label                    dev pos        method
CC_EXP_SPLIT_MONTH             0      identity
CC_EXP_SPLIT_YEAR              0      identity
COMPOSITE_UNSPLIT             72       sigmoid
NOT_AUTOFILLABLE              84       sigmoid
UNKNOWN                       60       sigmoid
additional-name                0      identity
address-level1                32       sigmoid
address-level2                44       sigmoid
address-line1                 24       sigmoid
address-line2                 24       sigmoid
address-line3                  0      identity
bday                           0      identity
cc-csc                        48       sigmoid
cc-exp                         0      identity
cc-exp-month                  24       sigmoid
cc-exp-year                   24       sigmoid
cc-name                        0      identity
cc-number                     48       sigmoid
cc-type                       24       sigmoid
country                       48       sigmoid
current-password               0      identity
email                         72       sigmoid
family-name                   56       sigmoid
given-name                    56       sigmoid
honorific-prefix              24       sigmoid
honorific-suffix              24       sigmoid
name                          24       sigmoid
new-password                  24       sigmoid
nickname                       0      identity
organization                  24       sigmoid
postal-code                   66       sigmoid
sex                            0      identity
tel                           24       sigmoid
tel-country-code              24       sigmoid
tel-extension                  0      identity
tel-national                  24       sigmoid
transaction-amount            24       sigmoid
url                           24       sigmoid
username                       0      identity
```

### 6.1 How well the numbers match reality

Reported, not merely performed, which is what `spec section 10.4` asks for. The
expected error below is the count-weighted mean gap between what the model said
and what happened.

```
results: models/dev_metrics.json
expected calibration error, before   0.0870
expected calibration error, after    0.0562
```

The reliability curve after calibration, over the winning class's probability:

```
results: models/dev_metrics.json
bin              count   predicted    observed
0.0 to 0.1           0
0.1 to 0.2          25       0.171       0.000
0.2 to 0.3          64       0.253       0.078
0.3 to 0.4         107       0.352       0.402
0.4 to 0.5          73       0.453       0.438
0.5 to 0.6         124       0.548       0.589
0.6 to 0.7          86       0.653       0.674
0.7 to 0.8          70       0.747       0.557
0.8 to 0.9         170       0.862       0.894
0.9 to 1.0         399       0.942       0.980
```

Two things in that curve deserve to be said rather than left for a reader to
find. The model remains **overconfident at the bottom**: in the two lowest
occupied bins it says roughly a fifth to a quarter and is right far less often
than that. And it is mildly **under**confident at the top, where it says
ninety-four and is right ninety-eight. The second of those is the direction that
costs nothing; the first is the direction that would matter, and it is the
argument for the high threshold sitting where it does rather than lower.

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
rows compared                        1118
rows agreeing on argmax              1118
largest per-class probability gap    3.576e-07
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
- **A label with no training rows.** Three labels in the dev split have no
  training row and the model predicts them never. A label the split did not put
  in train is a label this model cannot produce, and no amount of confidence
  changes that.
- **Composite and split controls.** `COMPOSITE_UNSPLIT` is the largest confusion
  in the table and it goes to `NOT_AUTOFILLABLE`. The structural difference lives
  in `group_role`, which is one feature against thousands of text features.
- **Custom widgets.** A control inside a closed shadow root or drawn on a canvas
  never reaches the model at all. The extractor reports it as undetectable and
  the engine short-circuits it, which is the honest outcome and is not a
  classification.
- **Telephone fields.** `tel` and `tel-national` differ by whether a dialling
  code is expected, which is a fact about the form's intent and is almost never
  in the markup. Both directions are in the confusion table and both have the
  lowest F1 scores of any label with training rows.

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
