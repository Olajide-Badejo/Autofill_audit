# 0008: the transformer stretch, its model, its dependencies, and where its code lives

Author: Olajide Badejo. Date: 2026-08-27. Phase P8. Status: accepted.

## Context

<!-- traceability: a specification section number, not a measurement -->
Spec section 10.7 makes the transformer conditional and says so in its title. A
distilled multilingual encoder, fine-tuned on the same splits, exported to ONNX
with dynamic INT8, trained on the RTX 5070 and served on the CPU like everything
else. It ships only if it wins a pre-stated metric by a pre-stated margin inside
a pre-stated latency budget, and if it does not, the deliverable is a paragraph
explaining that it did not.

The three bars are fixed in `experiments/predictions/p8-transformer.md`, which is
the first commit of this phase. This record covers the decisions the prediction
file deliberately left open: which encoder, which dependencies and where they
live, where the inference code lives before the condition is evaluated, and what
the engine can and cannot say about its own answers.

## Decision 1: the model is `distilbert-base-multilingual-cased`

The primary candidate of the phase brief, kept.

The brief allowed a multilingual MiniLM-class alternate if VRAM, tokenizer, or
export behaviour argued for it. None of the three did.

- **VRAM.** Fine-tuning 135 million parameters at batch 32 and 64 tokens peaks
  well inside a 12 GB card. There was never pressure here.
- **Tokenizer.** The WordPiece vocabulary loads through the `tokenizers` wheel
  and saves to a single `tokenizer.json` that the serving path reads directly.
  No sentencepiece model file, no second artefact.
- **Export.** It exports through the legacy `torch.onnx` path at opset 23 and
  loads in onnxruntime with the CPU provider on the first probe.

A fourth consideration argued the other way and was refused deliberately. A
smaller encoder would run faster, and one arm of the ship condition is a latency
budget. **Swapping to a smaller model to pass the latency arm would weaken the
accuracy arm, which is the arm that is the reason to ship at all.** The question
this phase asks is whether a distilled multilingual encoder beats a linear model
on the held-out locale by enough to be worth its cost. Answering a version of it
with a weaker model, chosen after seeing that the strong one was slow, would be
answering an easier question and reporting it under the original one's name. The
strong candidate gets the accuracy arm its best shot and the latency arm is
measured as it falls.

The two things that were varied, both on the dev split and both pre-registered
as dev-only choices: the learning rate and the sequence length, with the number
of epochs read off a per-epoch dev evaluation. The sequence-length grid is the
one place the latency trade is explored honestly, because a shorter sequence is
less arithmetic per field and the grid shows what it costs in dev macro-F1.

## Decision 2: the training dependencies are an extra CI never installs

`torch`, `transformers` and `tokenizers` go in a new `bert-train` extra in
`pyproject.toml`, outside `dev`, and **not** in `requirements.lock`.

The Makefile's `lock` target compiles `--extra dev --extra llm` and nothing
else, so the exclusion holds by construction rather than by remembering to leave
it out. CI installs `requirements.lock` in all six jobs and therefore never
installs any of the three.

The resolved versions of this phase, recorded here because the lock file cannot
record them:

| Package | Version |
|---|---|
| `torch` | `2.13.0+cu130` |
| `transformers` | `5.16.1` |
| `tokenizers` | `0.23.1` |
| `onnx` | `1.22.0` |
| `onnxruntime` | `1.29.0` |
| Python | `3.14.4` |

The same set is written into the train manifest beside the model, which is what
law 3 actually reads.

## Decision 3: the Blackwell check is a gate, not an assumption

<!-- traceability: a specification section number, not a measurement -->
The card is an RTX 5070, which is a Blackwell part reporting compute capability
`12.0`, and a torch wheel that predates that architecture fails at the first
kernel launch rather than at import. So the wheel is checked against the card
before anything long runs, and the check is a CUDA matmul plus one autograd
step rather than `torch.cuda.is_available()`, which answers a different and
easier question.

Recorded from the check on this machine: `torch 2.13.0+cu130`, built against
CUDA `13.0` and cuDNN `92000`, compiled for
`sm_75, sm_80, sm_86, sm_90, sm_100, sm_120`. The card reports `sm_120`, so it
is covered by a compiled architecture rather than by JIT compilation from PTX.
The matmul agreed with the CPU reference and the backward pass completed.

The pre-decided alternative, from the phase brief, was that a wheel with no
support for this card is a legitimate no-ship outcome with evidence, and that
what is not acceptable is hours of silent CPU training. It was not needed. The
training script still refuses to fall back: asking for `--device cuda` on a
machine without it exits rather than starting a run that would take a day.

## Decision 4: the inference code lives in `scripts/` until the condition is met

`scripts/bert_engine.py` holds the serialiser, the session and the engine, and
it sits beside the training script rather than in
`src/autofill_audit/classify/`.

The condition is not decided when the code is written, and a conditional engine
that has already moved into the package has quietly decided it. Putting it in
`src/` before the measurement would add `tokenizers` to the runtime dependency
list, put a second model format in the wheel, and make `--engine bert` appear in
the help text of a tool that has not established it has that engine. It would
also put a module CI cannot exercise inside the coverage gate.

`scripts/` is where the repository keeps code that measures rather than code
that ships, and until the three bars are evaluated that is exactly what this is.
If the ship condition is met, the module moves into
`src/autofill_audit/classify/` with its tests and `bert` joins `EngineChoice`,
and that move is the wiring the ship branch exists to do. If it is not met, the
module stays where it is, correctly labelled as the code that produced a
committed measurement.

The one thing that does not wait for the verdict is the `bert` block in
`src/autofill_audit/audit/thresholds.json`. The committed test-split run is
produced with it, and a threshold file that lost the block afterwards would make
that run unreproducible from the repository, which law 3 forbids. Its presence
is not a claim that the engine ships; `EngineChoice` is what makes that claim,
and the block's `basis` string says which state it is in. This was
pre-registered in the prediction file before the run for exactly the reason that
it would otherwise look like a decision made afterwards.

## Decision 5: the encoder is shown the P6 field view, and never the declaration

`field_text` renders the same signal set the language model receives at P6: the
intrinsics, the identifier attributes, every text signal, the option list
truncated with its true count alongside, and the structural position. Two text
models compared against each other on different views of the same field are not
being compared, and P6 already fixed what a text model is shown.

It renders that set itself rather than importing `llm/prompts.py::prune`, for
two reasons. The string layout is a modelling decision belonging to this engine,
not a reformatting of somebody else's JSON. And a module that may later move
into `src/` must not import the research layer, which ground rule 11 forbids.

**The asymmetry against the n-gram featuriser is real and is stated rather than
hidden.** The featuriser reads the normalised token blob and the *shape* of an
option list; this serialiser reads the unnormalised text signals and the first
few option labels. That is the same trade P6 made and defended: the normalisation
is a lossy preprocessing step that exists to make a bag of character n-grams
tractable, and a subword tokenizer reads `Postleitzahl` better than it reads the
pieces the normaliser splits it into. It is recorded here so that a reader of the
headline table knows the two engines are not reading identical bytes.

The declared `autocomplete` value is never rendered, and the property is checked
by independence before training starts: the string built from a descriptor and
the string built from the same descriptor with its declaration stripped must be
identical, on every train and dev row. A leak there would turn every clean-tier
number into a measurement of copying and would not look wrong in a diff.

## Decision 6: no fourth confidence kind, and the reason is not convenience

P7's handoff expected `evaluate/runlog.py`'s `_DESCRIBE_TO_KIND` to need a
deliberate new entry for a fourth engine. It does not, and adding one would be
wrong.

The mapping is total and raises on an unknown word precisely so that nothing
downstream pools a regex tier with a probability. This engine's confidences are
one-vs-rest calibrated probabilities fitted on the dev split by
`scripts/train.py::fit_calibration`, the identical procedure that produced the
n-gram engine's, with the identical switchover. They are the same kind of
quantity, so they report the same word, `calibrated-probability`, and the run log
records `calibrated`. Inventing a fourth word would assert a distinction that
does not exist, and would work against the thing the key is for.

The mapping was still read and confirmed rather than assumed, which is what the
handoff note was asking for.

## Decision 7: this engine cannot name its evidence, and says so

<!-- traceability: a specification section number, not a measurement -->
Law 1 requires every finding to carry a named evidence list, and the n-gram
engine satisfies it exactly: a contribution is the feature's value times the
class weight, which is the term that entered the logit, so its evidence is the
model's own account of itself. A transformer has no such decomposition available
without an attribution method this project has not built and would have to
validate before quoting.

So the engine records what is true: the input segments the field actually
carried, prefixed `bert:input:`, together with a `bert:attribution:unavailable`
marker on every prediction. That is a statement about what the model was shown
and not about what it did, the marker says so, and the model card and this record
say so in the same words spec section 10.2 uses about the hashing fallback: it is
a real cost, honestly stated.

If the engine had shipped, this would be the strongest argument against making
it the default even at equal accuracy, and it is worth writing down that the
argument survives the verdict either way.

## Consequences

- CI never installs a training stack and never sees a GPU. The cost is that two
  scripts are only exercised on the build machine, and the tests that need a
  tokenizer skip themselves elsewhere with a printed reason.
- The repository can rebuild the measurement but not from the lock file alone. A
  reader reproducing it needs the extra installed by hand at the versions in the
  table above.
- The INT8 graph is 135.8 MB. That is over GitHub's hard per-file limit for a
  push without large-file storage, so a shipping transformer would have needed a
  storage decision this project has so far not needed to make. The fact is
  recorded here because it is a real constraint on the ship path and it was
  discovered before the verdict rather than after it.
- The eval runner learns a fourth engine name and a `--bert-model` flag, and the
  threshold document learns a fourth block. Nothing else in `src/` changes.
