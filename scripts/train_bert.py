#!/usr/bin/env python3
"""Fine-tune the multilingual encoder of spec section 10.7, export it, quantize it.

The contract of spec section 10.3 applied to a second model family, with the
same partition discipline and the same guard:

```
inputs:   --corpus DIR  --split-file corpus/split.json  --seed INT  --out DIR
reads:    ONLY the train partition for fitting; ONLY the dev partition for
          calibration and for any hyperparameter choice
writes:   out/model.onnx, out/model.int8.onnx, out/tokenizer.json,
          out/label_map.json, out/calibration.json, out/bert_config.json,
          out/train_manifest.json, out/dev_metrics.json
forbids:  reading the test partition at all, enforced by the same audit hook
```

Everything about which fields exist, which are dropped, and what the truth is
comes from ``scripts/train.py``. This script imports those loaders rather than
reimplementing them, because two definitions of "which controls count" would set
two different denominators under one word, and the whole point of P8 is a
comparison against a number P4 produced.

What is fixed before the run and what is chosen on dev
-------------------------------------------------------

Fixed: the model family, the seed, the batch size, the optimiser, the schedule,
the class weighting, and the grids below. Chosen on **dev macro-F1**, which is
the rule ``experiments/predictions/p8-transformer.md`` section 4 pre-registers:
the learning rate, the sequence length, and the number of epochs. The epoch is
chosen by evaluating after every epoch of a single run rather than by training
one run per epoch count, which is the same choice made for a fraction of the
electricity, and every cell of the resulting grid is written into the manifest so
that the choice is visible rather than asserted.

The three exports, in the order they must happen
-------------------------------------------------

1. **FP32 ONNX**, checked against PyTorch on every dev row for exact argmax
   agreement. This is the P4 parity gate, unchanged in its demand: an export is
   not a result, and a graph that disagrees with the model that was trained is a
   different model with the same file name.
2. **Dynamic INT8**, checked against the FP32 graph on every dev row for an
   agreement rate and a macro-F1 delta inside pre-registered bounds. Exactness is
   not expected here and demanding it would be demanding that the quantizer not
   work.
3. **Calibration**, fitted on the dev outputs of the INT8 graph, because the INT8
   graph is what would serve and a confidence has to be a frequency claim about
   what the tool actually does (spec section 10.4).

Usage:
    train_bert.py --corpus corpus --split-file corpus/split.json --seed 20260825 \\
                  --out .scratch/p8/bundle --cache .scratch/descriptor-cache

Exit status is 0 when the run completes and the FP32 parity gate passes.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
import time
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import bert_engine  # noqa: E402
import train  # noqa: E402
from autofill_audit import __version__  # noqa: E402
from autofill_audit.classify.onnx_model import (  # noqa: E402
    CALIBRATION_FILE,
    LABEL_MAP_FILE,
    LABEL_MAP_SCHEMA_VERSION,
)

DEFAULT_BASE_MODEL = "distilbert-base-multilingual-cased"
"""The primary candidate of the phase brief, kept. ADR 0008 records why it was
not traded for a smaller encoder: a smaller one would have improved the arm of
the ship condition that is a budget and weakened the arm that is the reason to
ship at all, and a phase that quietly weakens the accuracy arm to pass the
latency arm is answering an easier question than the one it asked."""

LEARNING_RATES: tuple[float, ...] = (2e-5, 3e-5, 5e-5)
"""The learning-rate grid, fixed before the run. Three points spanning the band
every fine-tuning recipe for an encoder of this size sits in. A finer grid on
5402 training rows would be reading noise."""

SEQUENCE_LENGTHS: tuple[int, ...] = (32, 64)
"""The sequence-length grid, fixed before the run. 64 tokens holds a label, an
identifier and a short context line for every locale in this corpus; 32 holds the
label and the identifier and truncates the rest. Both are swept because the
choice trades dev macro-F1 against the arithmetic per field, and the trade is
worth showing rather than assuming."""

MAX_EPOCHS = 8
"""Every epoch is evaluated on dev and every one is a cell of the grid."""

BATCH_SIZE = 32
WEIGHT_DECAY = 0.01
WARMUP_FRACTION = 0.1
MAX_GRAD_NORM = 1.0

FP32_LOGIT_TOLERANCE = 1e-3
"""The pre-registered ceiling on the maximum absolute logit difference between
PyTorch and the FP32 ONNX graph. The gate is this plus exact argmax agreement on
every dev row."""

INT8_MIN_AGREEMENT = 0.99
INT8_MAX_MACRO_F1_DROP = 0.01
"""The pre-registered INT8 bounds. Both are recorded whichever way they land."""

PARITY_BATCH = 32

DEV_METRICS_FILE = "dev_metrics.json"
MANIFEST_FILE = "train_manifest.json"


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------


def seed_everything(seed: int) -> None:
    """Seed every generator this run draws from, and ask torch to be repeatable.

    ``warn_only`` on the deterministic-algorithm switch is deliberate. Some of
    the backward kernels an encoder uses have no deterministic implementation on
    this hardware, and the choice is between a run that warns about them and a
    run that refuses to start. A warning that names the operation is more useful
    than an abort, and the manifest records that the switch was set this way.
    """
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)


# ---------------------------------------------------------------------------
# The data, as the encoder sees it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Encoded:
    """One partition tokenised to fixed-width arrays."""

    input_ids: Any
    attention_mask: Any
    targets: Any
    truncated: int
    rows: int

    @property
    def truncation_rate(self) -> float:
        """The fraction of rows that lost tokens to the length cap."""
        return self.truncated / self.rows if self.rows else 0.0


def encode_partition(
    tokenizer: Any,
    texts: Sequence[str],
    labels: Sequence[str],
    classes: Sequence[str],
    max_length: int,
) -> Encoded:
    """Tokenise one partition to padded arrays, counting what was truncated."""
    index = {name: position for position, name in enumerate(classes)}
    batch = tokenizer(
        list(texts),
        padding="max_length",
        truncation=True,
        max_length=max_length,
        return_tensors="np",
    )
    unpadded = tokenizer(list(texts), padding=False, truncation=False)["input_ids"]
    truncated = sum(1 for row in unpadded if len(row) > max_length)
    return Encoded(
        input_ids=np.asarray(batch["input_ids"], dtype=np.int64),
        attention_mask=np.asarray(batch["attention_mask"], dtype=np.int64),
        targets=np.asarray([index[name] for name in labels], dtype=np.int64),
        truncated=truncated,
        rows=len(texts),
    )


def assert_tokenizer_parity(
    tokenizer: Any, tokenizer_path: Path, texts: Sequence[str], max_length: int
) -> dict[str, Any]:
    """Assert the training tokenizer and the runtime tokenizer agree exactly.

    The training path goes through ``transformers`` and the serving path goes
    through the ``tokenizers`` wheel reading the saved ``tokenizer.json``. They
    are two implementations of one contract, which is exactly the shape of the
    train and serve skew spec section 10.2 spends a page on for the featuriser.
    So it is checked rather than assumed, over every row this run will use.

    Raises:
        SystemExit: the two disagree on any row.
    """
    from tokenizers import Tokenizer

    runtime = Tokenizer.from_file(str(tokenizer_path))
    runtime.enable_truncation(max_length=max_length)
    training = tokenizer(list(texts), padding=False, truncation=True, max_length=max_length)
    encoded = runtime.encode_batch(list(texts))
    mismatched = [
        position
        for position, (left, right) in enumerate(zip(training["input_ids"], encoded, strict=True))
        if list(left) != list(right.ids)
    ]
    if mismatched:
        raise SystemExit(
            f"train_bert.py: the training tokenizer and {tokenizer_path.name} disagree on "
            f"{len(mismatched)} of {len(texts)} rows, first at index {mismatched[0]}. "
            "Serving would then read different tokens from the ones the weights were fitted "
            "on, which is the train and serve skew the single featuriser exists to prevent."
        )
    return {"rows": len(texts), "disagreements": 0, "max_length": max_length}


# ---------------------------------------------------------------------------
# Fitting.
# ---------------------------------------------------------------------------


def class_weights(targets: Any, class_count: int) -> Any:
    """The balanced weighting scikit-learn's ``class_weight='balanced'`` computes.

    The same weighting the n-gram model was fitted with, for the same reason: the
    headline metric is macro-F1, which is precisely the metric that punishes
    ignoring a rare class, and ``one-time-code`` is rare where ``email`` is not.
    Two engines compared on macro-F1 where only one of them weighted its loss
    would be a comparison of two loss functions.
    """
    counts = np.bincount(targets, minlength=class_count).astype(np.float64)
    total = float(len(targets))
    weights = np.where(counts > 0, total / (class_count * np.maximum(counts, 1.0)), 0.0)
    return weights


def build_model(base_model: str, class_count: int) -> Any:
    """Load the pretrained encoder with a fresh classification head."""
    from transformers import AutoModelForSequenceClassification

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return AutoModelForSequenceClassification.from_pretrained(
            base_model, num_labels=class_count
        )


def _predict_logits(model: Any, encoded: Encoded, device: Any, batch: int = 128) -> Any:
    """Run one partition through the torch model, returning logits as numpy."""
    import torch

    model.eval()
    outputs: list[Any] = []
    with torch.no_grad():
        for start in range(0, encoded.rows, batch):
            ids = torch.from_numpy(encoded.input_ids[start : start + batch]).to(device)
            mask = torch.from_numpy(encoded.attention_mask[start : start + batch]).to(device)
            logits = model(input_ids=ids, attention_mask=mask).logits
            outputs.append(logits.float().cpu().numpy())
    return np.concatenate(outputs, axis=0)


def fit_one(
    base_model: str,
    train_set: Encoded,
    dev_set: Encoded,
    classes: Sequence[str],
    dev_labels: Sequence[str],
    learning_rate: float,
    seed: int,
    device: Any,
) -> tuple[list[dict[str, Any]], float, int, Any]:
    """Train one configuration, evaluating on dev after every epoch.

    Returns the per-epoch grid cells, the best dev macro-F1, the epoch that
    produced it, and a CPU copy of the state dict at that epoch.
    """
    import torch
    from torch.optim import AdamW

    seed_everything(seed)
    model = build_model(base_model, len(classes)).to(device)
    weights = torch.tensor(
        class_weights(train_set.targets, len(classes)), dtype=torch.float32, device=device
    )
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = AdamW(model.parameters(), lr=learning_rate, weight_decay=WEIGHT_DECAY)

    steps_per_epoch = (train_set.rows + BATCH_SIZE - 1) // BATCH_SIZE
    total_steps = steps_per_epoch * MAX_EPOCHS
    warmup = max(1, int(total_steps * WARMUP_FRACTION))

    def schedule(step: int) -> float:
        if step < warmup:
            return step / warmup
        remaining = total_steps - warmup
        return max(0.0, (total_steps - step) / remaining) if remaining else 0.0

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
    generator = torch.Generator().manual_seed(seed)

    ids = torch.from_numpy(train_set.input_ids)
    mask = torch.from_numpy(train_set.attention_mask)
    targets = torch.from_numpy(train_set.targets)

    cells: list[dict[str, Any]] = []
    best_score = -1.0
    best_epoch = 0
    best_state: Any = None

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        order = torch.randperm(train_set.rows, generator=generator)
        running = 0.0
        started = time.perf_counter()
        for start in range(0, train_set.rows, BATCH_SIZE):
            chosen = order[start : start + BATCH_SIZE]
            optimizer.zero_grad(set_to_none=True)
            logits = model(
                input_ids=ids[chosen].to(device), attention_mask=mask[chosen].to(device)
            ).logits
            loss = loss_fn(logits, targets[chosen].to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), MAX_GRAD_NORM)
            optimizer.step()
            scheduler.step()
            running += float(loss.detach()) * len(chosen)
        elapsed = time.perf_counter() - started

        logits = _predict_logits(model, dev_set, device)
        predicted = [classes[int(index)] for index in logits.argmax(axis=1)]
        score = train._macro_f1(dev_labels, predicted)
        accuracy = float(np.mean(np.asarray(predicted) == np.asarray(dev_labels)))
        cells.append(
            {
                "learning_rate": learning_rate,
                "epoch": epoch,
                "train_loss": running / train_set.rows,
                "dev_macro_f1": score,
                "dev_accuracy": accuracy,
                "epoch_seconds": elapsed,
            }
        )
        print(
            f"    epoch {epoch}/{MAX_EPOCHS}  loss {running / train_set.rows:.4f}  "
            f"dev macro-F1 {score:.4f}  dev accuracy {accuracy:.4f}  {elapsed:.1f}s"
        )
        if score > best_score:
            best_score = score
            best_epoch = epoch
            best_state = {
                key: value.detach().cpu().clone() for key, value in model.state_dict().items()
            }

    del model, optimizer, scheduler
    torch.cuda.empty_cache()
    return cells, best_score, best_epoch, best_state


# ---------------------------------------------------------------------------
# Export, parity, quantization.
# ---------------------------------------------------------------------------


def export_onnx(model: Any, destination: Path, max_length: int) -> int:
    """Export the encoder at the newest opset onnxruntime will accept.

    Probed rather than copied, exactly as ``scripts/train.py`` probes, so the
    recorded number is a fact about this machine's resolved versions.
    """
    import onnx
    import onnxruntime
    import torch

    class Wrapper(torch.nn.Module):
        """Two named inputs and one named output, which is all the graph needs."""

        def __init__(self, inner: Any) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            """Return the logits alone, without the dataclass around them."""
            return self.inner(input_ids=input_ids, attention_mask=attention_mask).logits

    wrapper = Wrapper(model).eval()
    ids = torch.ones((2, max_length), dtype=torch.long)
    mask = torch.ones((2, max_length), dtype=torch.long)
    highest = min(int(onnx.defs.onnx_opset_version()), 23)
    failures: list[str] = []
    for opset in range(highest, highest - 8, -1):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                torch.onnx.export(
                    wrapper,
                    (ids, mask),
                    str(destination),
                    input_names=["input_ids", "attention_mask"],
                    output_names=["logits"],
                    dynamic_axes={
                        "input_ids": {0: "batch", 1: "sequence"},
                        "attention_mask": {0: "batch", 1: "sequence"},
                        "logits": {0: "batch"},
                    },
                    opset_version=opset,
                    dynamo=False,
                )
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 1
            onnxruntime.InferenceSession(
                str(destination), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:
            failures.append(f"opset {opset}: {type(error).__name__}: {error}")
            continue
        for line in failures:
            print(f"  probe rejected {line}")
        print(f"  probe accepted opset {opset}")
        return opset
    raise SystemExit(
        "no opset in the probed range converted and loaded:\n  " + "\n  ".join(failures)
    )


def quantize(source: Path, destination: Path) -> dict[str, Any]:
    """Apply dynamic INT8 quantization, recording what it did to the file.

    ``quant_pre_process`` runs with symbolic shape inference skipped. It is the
    documented preprocessing step, it fails on this graph with symbolic shape
    inference on, and the failure is recorded here rather than worked around
    silently: the shapes it cannot infer are the dynamic batch and sequence axes
    that are the whole point of the export.
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.quantization.shape_inference import quant_pre_process

    prepared = source.with_name("prepared.onnx")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        quant_pre_process(str(source), str(prepared), skip_symbolic_shape=True)
        quantize_dynamic(str(prepared), str(destination), weight_type=QuantType.QInt8)
    sizes = {
        "fp32_bytes": source.stat().st_size,
        "int8_bytes": destination.stat().st_size,
        "weight_type": "QInt8",
        "mode": "dynamic: weights quantized, activations quantized at run time",
        "pre_process": "quant_pre_process with skip_symbolic_shape=True",
    }
    prepared.unlink(missing_ok=True)
    return sizes


def session_logits(path: Path, encoded: Encoded, batch: int = PARITY_BATCH) -> Any:
    """Run one partition through an onnxruntime CPU session, threads pinned."""
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    output = str(session.get_outputs()[0].name)
    outputs: list[Any] = []
    for start in range(0, encoded.rows, batch):
        feed = {
            "input_ids": encoded.input_ids[start : start + batch],
            "attention_mask": encoded.attention_mask[start : start + batch],
        }
        outputs.append(np.asarray(session.run([output], feed)[0], dtype=np.float64))
    return np.concatenate(outputs, axis=0)


def parity_report(torch_logits: Any, onnx_logits: Any) -> dict[str, Any]:
    """The FP32 gate: exact argmax agreement plus a bounded logit difference."""
    rows = int(torch_logits.shape[0])
    agreements = int((torch_logits.argmax(axis=1) == onnx_logits.argmax(axis=1)).sum())
    delta = float(np.max(np.abs(torch_logits - onnx_logits)))
    return {
        "rows": rows,
        "argmax_agreements": agreements,
        "argmax_agreement_rate": agreements / max(rows, 1),
        "max_absolute_logit_delta": delta,
        "tolerance": FP32_LOGIT_TOLERANCE,
        "passed": agreements == rows and delta <= FP32_LOGIT_TOLERANCE,
    }


def quantization_report(
    fp32_logits: Any,
    int8_logits: Any,
    classes: Sequence[str],
    dev_labels: Sequence[str],
) -> dict[str, Any]:
    """The INT8 bounds: an agreement rate and a macro-F1 delta, both recorded."""
    rows = int(fp32_logits.shape[0])
    agreements = int((fp32_logits.argmax(axis=1) == int8_logits.argmax(axis=1)).sum())
    rate = agreements / max(rows, 1)
    fp32_macro = train._macro_f1(
        dev_labels, [classes[int(index)] for index in fp32_logits.argmax(axis=1)]
    )
    int8_macro = train._macro_f1(
        dev_labels, [classes[int(index)] for index in int8_logits.argmax(axis=1)]
    )
    drop = fp32_macro - int8_macro
    return {
        "rows": rows,
        "argmax_agreements": agreements,
        "argmax_agreement_rate": rate,
        "minimum_agreement_rate": INT8_MIN_AGREEMENT,
        "fp32_dev_macro_f1": fp32_macro,
        "int8_dev_macro_f1": int8_macro,
        "dev_macro_f1_drop": drop,
        "maximum_drop": INT8_MAX_MACRO_F1_DROP,
        "max_absolute_logit_delta": float(np.max(np.abs(fp32_logits - int8_logits))),
        "within_bounds": rate >= INT8_MIN_AGREEMENT and drop <= INT8_MAX_MACRO_F1_DROP,
    }


# ---------------------------------------------------------------------------
# The bundle.
# ---------------------------------------------------------------------------


def write_bundle(
    out: Path,
    tokenizer: Any,
    classes: Sequence[str],
    calibration: Any,
    max_length: int,
    base_model: str,
    quantization: Mapping[str, Any],
) -> None:
    """Write everything the engine loads, and nothing it does not."""
    (out / LABEL_MAP_FILE).write_text(
        json.dumps(
            {"schema_version": LABEL_MAP_SCHEMA_VERSION, "labels": list(classes)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / CALIBRATION_FILE).write_text(
        json.dumps(calibration.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / bert_engine.CONFIG_FILE).write_text(
        json.dumps(
            {
                "schema_version": bert_engine.CONFIG_SCHEMA_VERSION,
                "base_model": base_model,
                "max_length": max_length,
                "quantization": "int8-dynamic",
                "serialisation": (
                    "scripts/bert_engine.py::field_text, the P6 field view rendered as a "
                    "string. The declared autocomplete value is never rendered and the "
                    "independence of the rendering from it is asserted before training."
                ),
                "quantization_detail": dict(quantization),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _ = tokenizer


def measure_latency(bundle_dir: Path, examples: Sequence[train.Example]) -> dict[str, Any]:
    """Run the finished engine per form and collect the per-field latencies.

    A preview of the number the ship condition is defined on, produced by the
    same code path the evaluation runner uses: one ``predict`` call per form,
    elapsed time divided by the form's field count. It is a preview and not the
    gate, because the gate is the committed test-split figure, and it is here so
    that the trade the sequence-length grid makes is visible on dev.
    """
    engine = bert_engine.load_bert_engine(bundle_dir)
    by_form: dict[str, list[train.Example]] = {}
    for item in examples:
        by_form.setdefault(item.form_id, []).append(item)
    latencies: list[float] = []
    for group in by_form.values():
        for prediction in engine.predict([item.descriptor for item in group]):
            if prediction.latency_us is not None:
                latencies.append(prediction.latency_us)
    ordered = sorted(latencies)

    def percentile(fraction: float) -> float:
        if not ordered:
            return 0.0
        position = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
        return ordered[position]

    return {
        "fields": len(ordered),
        "forms": len(by_form),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "mean": float(np.mean(ordered)) if ordered else 0.0,
        "note": (
            "microseconds per field, a per-field share of one batched predict call per "
            "form, onnxruntime CPU execution provider with intra and inter op threads "
            "pinned to one. The same convention the n-gram engine's figure uses."
        ),
    }


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line. There is no --test flag and there will not be one."""
    parser = argparse.ArgumentParser(description="Fine-tune the encoder of spec section 10.7.")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--split-file", type=Path, default=None)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--base-model", type=str, default=DEFAULT_BASE_MODEL)
    parser.add_argument(
        "--device", type=str, default="cuda", help="cuda for training; the export is CPU either way"
    )
    return parser.parse_args(argv)


def _device_facts(device: Any) -> dict[str, Any]:
    """What the GPU was, and what torch was built against, for the manifest."""
    import torch

    facts: dict[str, Any] = {
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "compiled_architectures": list(torch.cuda.get_arch_list()),
        "device": str(device),
    }
    if str(device).startswith("cuda") and torch.cuda.is_available():
        index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(index)
        facts.update(
            {
                "gpu_name": torch.cuda.get_device_name(index),
                "compute_capability": f"{properties.major}.{properties.minor}",
                "total_vram_mib": properties.total_memory // (1024 * 1024),
            }
        )
    return facts


def main(argv: Sequence[str] | None = None) -> int:
    """Fine-tune, export, quantize, calibrate, and write every artefact."""
    args = _arguments(argv)
    import torch
    from transformers import AutoTokenizer

    corpus_dir: Path = args.corpus
    split_path: Path = args.split_file if args.split_file else corpus_dir / "split.json"
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    started = datetime.now(UTC)
    split = train._load_split(split_path)
    guard = train.TestPartitionGuard(frozenset(train._forms_in(split, train.TEST)))
    guard.arm()
    print(f"train_bert.py: guarding {len(guard.forbidden)} test-partition forms")

    manifest_document = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    base_year = int(manifest_document.get("base_year", time.gmtime().tm_year))
    train.bind_cache(args.cache, train._corpus_manifest_sha(corpus_dir))

    print(f"train_bert.py: extracting the {train.TRAIN} partition")
    train_set = train.build_dataset(corpus_dir, split, train.TRAIN, guard, args.cache, base_year)
    print(f"  {train_set.forms} forms, {len(train_set.examples)} rows")
    print(f"train_bert.py: extracting the {train.DEV} partition")
    dev_set = train.build_dataset(corpus_dir, split, train.DEV, guard, args.cache, base_year)
    print(f"  {dev_set.forms} forms, {len(dev_set.examples)} rows")

    bert_engine.assert_no_declaration_leaks(train_set.descriptors)
    bert_engine.assert_no_declaration_leaks(dev_set.descriptors)
    print("train_bert.py: the rendered field is independent of the declared autocomplete value")

    train_texts = bert_engine.field_texts(train_set.descriptors)
    dev_texts = bert_engine.field_texts(dev_set.descriptors)
    classes = sorted(set(train_set.labels))
    print(f"train_bert.py: {len(classes)} classes fitted from the train partition")

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    facts = _device_facts(device)
    print(f"train_bert.py: torch {facts['torch']} cuda {facts['torch_cuda']} on {device}")
    if str(device) == "cpu" and args.device.startswith("cuda"):
        print(
            "train_bert.py: cuda was asked for and is not available. Refusing to spend "
            "hours on the CPU silently; see the phase brief.",
            file=sys.stderr,
        )
        return 2

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    sweep: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    encodings: dict[int, tuple[Encoded, Encoded]] = {}
    for max_length in SEQUENCE_LENGTHS:
        encoded_train = encode_partition(
            tokenizer, train_texts, train_set.labels, classes, max_length
        )
        encoded_dev = encode_partition(tokenizer, dev_texts, dev_set.labels, classes, max_length)
        encodings[max_length] = (encoded_train, encoded_dev)
        print(
            f"train_bert.py: sequence length {max_length}, "
            f"train truncation {encoded_train.truncation_rate:.4f}, "
            f"dev truncation {encoded_dev.truncation_rate:.4f}"
        )
        for learning_rate in LEARNING_RATES:
            print(f"  lr {learning_rate:g} length {max_length}")
            cells, score, epoch, state = fit_one(
                args.base_model,
                encoded_train,
                encoded_dev,
                classes,
                dev_set.labels,
                learning_rate,
                args.seed,
                device,
            )
            for cell in cells:
                cell["max_length"] = max_length
            sweep.extend(cells)
            if best is None or score > best["dev_macro_f1"]:
                best = {
                    "learning_rate": learning_rate,
                    "max_length": max_length,
                    "epochs": epoch,
                    "dev_macro_f1": score,
                    "state": state,
                }
            else:
                del state

    if best is None:  # pragma: no cover - the grids are not empty
        raise SystemExit("train_bert.py: the sweep produced nothing")
    print(
        f"train_bert.py: chose lr {best['learning_rate']:g}, length {best['max_length']}, "
        f"{best['epochs']} epochs, dev macro-F1 {best['dev_macro_f1']:.4f}"
    )

    max_length = int(best["max_length"])
    encoded_train, encoded_dev = encodings[max_length]

    model = build_model(args.base_model, len(classes))
    model.load_state_dict(best["state"])
    model.eval()

    tokenizer.save_pretrained(out)
    tokenizer_parity = assert_tokenizer_parity(
        tokenizer, out / bert_engine.TOKENIZER_FILE, dev_texts, max_length
    )
    print(
        f"train_bert.py: tokenizer parity over {tokenizer_parity['rows']} dev rows, 0 disagreements"
    )

    fp32_path = out / bert_engine.MODEL_FP32_FILE
    opset = export_onnx(model, fp32_path, max_length)
    torch_logits = _predict_logits(model, encoded_dev, torch.device("cpu"), batch=PARITY_BATCH)
    fp32_logits = session_logits(fp32_path, encoded_dev)
    parity = parity_report(torch_logits, fp32_logits)
    print(
        f"train_bert.py: FP32 parity over {parity['rows']} dev rows, "
        f"argmax agreements {parity['argmax_agreements']}, "
        f"max logit delta {parity['max_absolute_logit_delta']:.3e}"
    )
    if not parity["passed"]:
        raise SystemExit("train_bert.py: the FP32 parity gate failed; the export is not the model")

    int8_path = out / bert_engine.MODEL_INT8_FILE
    sizes = quantize(fp32_path, int8_path)
    int8_logits = session_logits(int8_path, encoded_dev)
    quantized = quantization_report(fp32_logits, int8_logits, classes, dev_set.labels)
    print(
        f"train_bert.py: INT8 agreement {quantized['argmax_agreement_rate']:.4f} "
        f"(bar {INT8_MIN_AGREEMENT}), dev macro-F1 drop "
        f"{quantized['dev_macro_f1_drop']:+.4f} (bar {INT8_MAX_MACRO_F1_DROP})"
    )
    print(
        f"train_bert.py: fp32 {sizes['fp32_bytes'] / 1e6:.1f} MB, "
        f"int8 {sizes['int8_bytes'] / 1e6:.1f} MB"
    )

    raw_dev = bert_engine.softmax(int8_logits)
    calibration = train.fit_calibration(raw_dev, dev_set.labels, classes)
    calibrated_dev = calibration.apply(raw_dev)
    raw_predictions = [classes[int(index)] for index in np.argmax(raw_dev, axis=1)]
    calibrated_predictions = [classes[int(index)] for index in np.argmax(calibrated_dev, axis=1)]

    macro = train._macro_f1(dev_set.labels, calibrated_predictions)
    accuracy = sum(
        1 for a, b in zip(dev_set.labels, calibrated_predictions, strict=True) if a == b
    ) / max(len(dev_set.labels), 1)
    print(f"train_bert.py: dev macro-F1 {macro:.4f}, dev accuracy {accuracy:.4f}")

    write_bundle(out, tokenizer, classes, calibration, max_length, args.base_model, sizes)
    latency = measure_latency(out, dev_set.examples)
    print(
        f"train_bert.py: dev latency per field p50 {latency['p50']:.0f} us, "
        f"p95 {latency['p95']:.0f} us, p99 {latency['p99']:.0f} us"
    )

    metrics = {
        "schema_version": 1,
        "split": train.DEV,
        "engine": bert_engine.ENGINE_NAME,
        "generated_on": started.date().isoformat(),
        "corpus_manifest_sha256": train._corpus_manifest_sha(corpus_dir),
        "counts": {
            "train_forms": train_set.forms,
            "train_rows": len(train_set.examples),
            "dev_forms": dev_set.forms,
            "dev_rows": len(dev_set.examples),
            "excluded_forms": len(train._forms_in(split, train.EXCLUDED)),
            "classes_fitted": len(classes),
            "labels_in_dev_only": sorted(set(dev_set.labels) - set(train_set.labels)),
            "train_truncation_rate": encoded_train.truncation_rate,
            "dev_truncation_rate": encoded_dev.truncation_rate,
        },
        "sweep": {
            "learning_rates": list(LEARNING_RATES),
            "sequence_lengths": list(SEQUENCE_LENGTHS),
            "max_epochs": MAX_EPOCHS,
            "batch_size": BATCH_SIZE,
            "selected_on": "dev macro-F1",
            "cells": sweep,
            "chosen": {
                "learning_rate": best["learning_rate"],
                "max_length": max_length,
                "epochs": best["epochs"],
            },
        },
        "headline": {"dev_macro_f1": macro, "dev_accuracy": accuracy},
        "per_label": train.per_label_report(
            dev_set.labels, calibrated_predictions, train_set.labels
        ),
        "slices": {
            "per_locale": train.slice_report(dev_set.examples, calibrated_predictions, "locale"),
            "per_tier": train.slice_report(dev_set.examples, calibrated_predictions, "tier"),
        },
        "insufficient_data_minimum": train.INSUFFICIENT_DATA_MINIMUM,
        "calibration": {
            "switchover_count": train.ISOTONIC_SWITCHOVER,
            "fitted_on": "the dev outputs of the INT8 graph, which is what would serve",
            "methods": calibration.methods(),
            "dev_positives": {item.label: item.dev_positives for item in calibration.classes},
            "before": train.reliability(raw_dev, dev_set.labels, classes),
            "after": train.reliability(calibrated_dev, dev_set.labels, classes),
            "macro_f1_before_calibration": train._macro_f1(dev_set.labels, raw_predictions),
        },
        "abstention": train._abstention(dev_set.labels, calibrated_predictions),
        "confusions": train.confusion_pairs(dev_set.labels, calibrated_predictions),
        "tokenizer_parity": tokenizer_parity,
        "parity": parity,
        "quantization": {**quantized, **sizes},
        "latency_us_per_field_dev": latency,
    }
    (out / DEV_METRICS_FILE).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    finished = datetime.now(UTC)
    peak = int(torch.cuda.max_memory_allocated() // (1024 * 1024)) if device.type == "cuda" else 0
    manifest = {
        "schema_version": 1,
        "tool_version": __version__,
        "engine": bert_engine.ENGINE_NAME,
        "git_sha": train._git("rev-parse", "HEAD"),
        "git_dirty": train._dirty(out),
        "seed": args.seed,
        "corpus_manifest_sha256": train._corpus_manifest_sha(corpus_dir),
        "split_file_sha256": train._sha256_of(split_path),
        "split_counts": split.get("form_counts", {}),
        "held_out_locale": split.get("held_out_locale"),
        "excluded_partition_used_for": "nothing at P8, as at P4",
        "base_model": args.base_model,
        "serialisation": "scripts/bert_engine.py::field_text",
        "sweep_grid": {
            "learning_rates": list(LEARNING_RATES),
            "sequence_lengths": list(SEQUENCE_LENGTHS),
            "max_epochs": MAX_EPOCHS,
        },
        "chosen_hyperparameters": {
            "learning_rate": best["learning_rate"],
            "max_length": max_length,
            "epochs": best["epochs"],
            "batch_size": BATCH_SIZE,
            "optimizer": "AdamW",
            "weight_decay": WEIGHT_DECAY,
            "schedule": "linear decay with a warmup of a tenth of the total steps",
            "loss": "cross entropy with balanced class weights",
            "max_grad_norm": MAX_GRAD_NORM,
        },
        "calibration_switchover": train.ISOTONIC_SWITCHOVER,
        "onnx_opset": opset,
        "quantization": dict(sizes),
        "dependencies": _dependency_versions(),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unrecorded",
            "cpu_count": os.cpu_count() or 0,
            "gpu_used": device.type == "cuda",
            **facts,
            "peak_vram_mib": peak,
        },
        "determinism": (
            "seeds set for python, numpy and torch; cudnn deterministic; "
            "use_deterministic_algorithms with warn_only, because some encoder backward "
            "kernels have no deterministic implementation on this hardware"
        ),
        "command_line": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "wall_seconds": (finished - started).total_seconds(),
    }
    (out / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
        print(
            f"train_bert.py: peak VRAM {peak} MiB, "
            f"now {torch.cuda.memory_allocated() // (1024 * 1024)} MiB allocated"
        )
    print(f"train_bert.py: wrote the bundle to {out}")
    return 0


def _dependency_versions() -> dict[str, str]:
    """The resolved versions of everything this run depended on."""
    from importlib.metadata import PackageNotFoundError, version

    names = (
        "numpy",
        "onnx",
        "onnxruntime",
        "playwright",
        "scikit-learn",
        "tokenizers",
        "torch",
        "transformers",
    )
    resolved: dict[str, str] = {"python": platform.python_version()}
    for name in names:
        try:
            resolved[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - all of them are installed here
            resolved[name] = "absent"
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
