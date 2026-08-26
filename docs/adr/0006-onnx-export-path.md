# 0006: the ONNX export path, and the opset the probe accepted

Date: 2026-08-26. Phase P4. Status: accepted.

## Context

Spec section 10.5 names two things that are known to go wrong when a
scikit-learn text pipeline is exported to ONNX, and gives each a pre-decided
response.

**Sharp edge 1 is the text vectorizer.** skl2onnx's converters for
`CountVectorizer` and `TfidfVectorizer` support a documented subset of
scikit-learn's behaviour, and the character-analyser variants in particular are
where the ONNX graph's semantics and scikit-learn's Python-level regex tokenizer
can diverge. The specification's instruction is blunt: do not assume the export
is faithful because it succeeded, make the gate a parity test, and if parity
cannot be reached take the fallback **quickly** rather than spending a day
coaxing a converter.

**Sharp edge 2 is the opset.** Export at the newest opset the resolved
onnxruntime accepts, determined by a probe on the build machine rather than
copied from anywhere.

## Decision

**The hand-rolled featuriser route was taken, and it was taken at the design
stage rather than after a failed attempt.** No vectorizer is in the exported
graph. `classify/features.py` enumerates the character and word n-grams in plain
Python, on both sides of the train/serve boundary, and the graph holds the linear
layer and nothing else.

**The graph is exported at opset 26**, which is what the probe accepted.

## Why the route was chosen rather than discovered

Three reasons, and the first is decisive on its own.

**The feature set was never convertible.** Spec section 10.2 has five feature
blocks. Two are text vectorisers; the other three are categorical one-hots,
option-shape booleans, and structural buckets, and no scikit-learn transformer
produces them. Putting the whole featurisation in the graph would have meant
writing custom skl2onnx converters for three bespoke transformers as well as
trusting the vectorizer converters, which is a larger version of exactly the risk
section 10.5 warns about. The fallback's Python featuriser is not a retreat from
that design; it is the only design in which one implementation serves both paths,
which section 10.2 required from the start.

**The runtime dependency list.** A vectorizer outside the graph but inside the
inference path would put scikit-learn on the dependency list of a tool that
installs with `pipx`. The hand-rolled route means an installed wheel needs numpy
and onnxruntime and nothing else. That is the deployment argument of spec section
5.4 applied to one more package, and it is worth the vectorizer's C speed on a
page with sixty controls.

**What is left to be wrong is small and checkable.** A graph containing one
`LinearClassifier` node converts trivially and faithfully, and the parity test
over the full dev split then has something narrow to prove rather than a
tokenizer's worth of semantics.

The cost is real and is recorded rather than waved past: the Python analyser is
slower than scikit-learn's C implementation, and its faithfulness to `char_wb` is
a claim rather than an identity. That claim is tested. `tests/unit/test_features.py`
asserts, over ten inputs including empty strings, words shorter than the n-gram
length, and Japanese text, that the enumeration this project performs is
character-for-character the enumeration scikit-learn performs, with lowercasing
disabled because the token stream arrives already casefolded and its stream
prefixes are uppercase on purpose.

## The evidence

### The opset probe

The probe walks down from the newest opset the installed `onnx` package defines,
and takes the first that both converts and opens in an onnxruntime session. It
ran on the build machine at training time and its output is the record:

```
probe rejected opset 27: Fail: [ONNXRuntimeError] : 1 : FAIL :
  ONNX Runtime only *guarantees* support for models stamped with official
  released onnx opset versions. Opset 27 is under development and support for
  this is limited. ... Current official support for domain ai.onnx is till
  opset 26.
probe accepted opset 26
```

skl2onnx emits a warning at both attempts saying that the requested opset is
above the latest version it has been tested against. The warning is recorded here
rather than suppressed, and it is the reason the parity gate is the thing that
decides, not the export: an untested-but-accepted opset is precisely a case where
"it converted" proves nothing and "it agrees on every row" proves what matters.

### What the graph turned out to be

```
ir_version    13
opset         ai.onnx 26, ai.onnx.ml 1
producer      skl2onnx 1.20.0
input         features, shape [batch, 6656], float32
outputs       label [batch], probabilities [batch, 39]
nodes         ai.onnx.ml.LinearClassifier (post_transform SOFTMAX)
              ai.onnx.ml.Normalizer (norm L1)
```

The coefficients, the intercepts, and the class order live in the
`LinearClassifier` node's **attributes**, not in graph initialisers. That is a
detail with a consequence: onnxruntime does not hand a caller a node's
attributes, so the inference path cannot read its own weights, and naming the
n-grams behind a prediction would otherwise require the `onnx` package at
runtime. `models/evidence.json` exists for that reason, carrying each class's
highest weighted features, written by the same training run, and checked against
the graph by the parity suite so that a stale copy fails the build rather than
naming the wrong n-grams in a report.

### The parity gate

The whole dev split, scikit-learn against onnxruntime, row by row:

```
results: models/dev_metrics.json
rows compared                        1118
rows agreeing on argmax              1118
argmax agreement rate                1.0
largest per-class probability gap    3.576e-07
tolerance                            1.0e-05
```

The gap is two orders of magnitude inside the tolerance, and its size is what a
float32 graph against a float64 estimator should produce over a few thousand
nonzero terms. A gap much smaller would have suggested the two sides were not
independent; a gap much larger would have suggested a semantic difference rather
than an arithmetic one.

Because the fitted scikit-learn estimator is deliberately not committed (a pickle
binds the artefact to one scikit-learn version, which spec section 5.4 calls a
hostile property for a tool meant to be installed years later), that comparison
runs once, at training time, and its result is committed. The committed test
suite asserts the record is a passing one, and separately re-runs the comparison
against a numpy reference built from the graph's own coefficients over
descriptors extracted from the sample corpus through a real browser. The second
half is what keeps working after the training machine is gone: it catches an
onnxruntime upgrade that changes what `LinearClassifier` means, which is a
failure the recorded record cannot notice.

## The session

Created with the CPU execution provider named explicitly and intra-op threads
pinned to one, per spec section 10.5. A per-field classification is far too small
to benefit from threading, and thread-pool spin-up would dominate the measurement
and make the latency numbers meaningless. Inter-op threads are pinned to one for
the same reason.

## Consequences

- Featurisation is Python and is slower than a C vectorizer. Measured informally
  and recorded in the engineering log rather than claimed here.
- The wheel's inference path depends on numpy and onnxruntime and nothing else.
- The exported graph is small enough to read and simple enough to reason about,
  and a reviewer can extract its weights with the `onnx` package in four lines.
- `models/evidence.json` is a derived file that must be regenerated with the
  model. The parity suite enforces that.
- **The release wheel does not currently carry the model.** The artefacts are
  committed under `models/` at the repository root, and the engine finds them by
  walking up from the working directory or from the installed package, or through
  `AUTOFILL_AUDIT_MODEL_DIR`. A `pipx` install therefore finds no model and
  `--engine auto` falls back to the rule baseline with its printed notice, which
  is the documented behaviour of spec section 10.1 rather than a failure. Whether
  a published wheel should ship a model is a packaging decision with a size cost
  and a release-cadence cost, it is not P4's to make, and P7 makes it.

## Alternatives rejected

**Convert the vectorizers and write three custom converters.** Rejected on the
first reason above: it is a larger version of the risk section 10.5 warns about,
and section 10.5 explicitly says the fallback should be taken quickly rather than
fought.

**Hashing features instead of a vocabulary.** The recorded fallback of spec
section 10.2, and not needed. The fitted vocabulary is 6656 columns, which is
small enough to commit and read. Hashing would have cost per-feature evidence,
which law 1 needs and which the model card would then have had to state as an
unavailability.

**Pickle the scikit-learn pipeline instead of exporting.** Rejected by spec
section 5.4 before this phase started. A pickle binds the runtime to the exact
scikit-learn version that created it.
