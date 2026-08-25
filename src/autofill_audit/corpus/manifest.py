"""The corpus manifest and the writer that produces a corpus directory.

Spec section 18: the generator writes ``corpus/manifest.json`` carrying the
seed, the generator version, the realised grid with per-cell counts, a sha256
per form, and the split assignment's sha. Two corpora with the same manifest sha
are the same corpus.

**Nothing here records a timestamp**, and that is deliberate rather than an
oversight. Ground rule 7 says same seed, same bytes, and P1's gate is the
generator run twice with the two outputs diffed. A generation timestamp in the
manifest would fail that gate on every run while telling a reader nothing they
could not get from git.

**The realised grid lives here and not in the documentation.** Spec section 8.5
says so explicitly: record the realised grid in the manifest, not in the
specification. The same reasoning extends to ``docs/``, where law 3 would in any
case require a number to trace to a result file.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from autofill_audit.corpus.answer_key import build_answer_key, validate_answer_key
from autofill_audit.corpus.generator import (
    GENERATOR_VERSION,
    GeneratedForm,
    GridSpec,
    iter_forms,
)
from autofill_audit.corpus.split import build_split, split_sha256
from autofill_audit.taxonomy import ALL_LABELS, Label

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "WriteResult",
    "label_coverage",
    "write_corpus",
    "write_json",
]

MANIFEST_SCHEMA_VERSION: Final[int] = 1

_JSON_INDENT: Final[int] = 2


def _dump(document: Any) -> str:
    """Serialise a JSON document the one way this project writes JSON.

    ``sort_keys`` because a dictionary's insertion order is not part of its
    meaning and a reordering would show up as a spurious diff. ``ensure_ascii``
    off because the corpus is deliberately multilingual and escaping Japanese
    labels into ``\\uXXXX`` would make the keys unreadable to the one audience
    that needs to read them.
    """
    return json.dumps(document, indent=_JSON_INDENT, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, document: Any) -> str:
    """Write a JSON document and return its sha256."""
    text = _dump(document)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def label_coverage(keys: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count how many answer-key entries carry each label.

    Every label in the taxonomy appears in the result, including the ones with a
    count of zero, because law 2 clause (b) is a statement about the labels that
    are *missing* and a mapping that omitted them would make the missing set
    impossible to compute from the output.
    """
    counts = Counter(entry["label"] for document in keys for entry in document["fields"])
    return {label.value: counts.get(label.value, 0) for label in sorted(ALL_LABELS)}


class WriteResult:
    """What one generation run produced."""

    __slots__ = ("form_count", "manifest", "manifest_sha", "split")

    def __init__(
        self,
        manifest: dict[str, Any],
        split: dict[str, Any],
        manifest_sha: str,
        form_count: int,
    ) -> None:
        self.manifest = manifest
        self.split = split
        self.manifest_sha = manifest_sha
        self.form_count = form_count

    def missing_labels(self) -> list[str]:
        """Return the labels no answer key emitted, sorted."""
        coverage: dict[str, int] = self.manifest["label_coverage"]
        return sorted(name for name, count in coverage.items() if count == 0)


def write_corpus(grid: GridSpec, out: Path) -> WriteResult:
    """Generate a corpus into ``out`` and return its manifest.

    The write order is fixed by ``GridSpec.cells``, so two runs of the same
    grid produce the same files in the same order with the same bytes.
    """
    forms_dir = out / "forms"
    keys_dir = out / "answer_keys"
    forms_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    forms: list[GeneratedForm] = []
    documents: list[dict[str, Any]] = []
    per_form: dict[str, dict[str, Any]] = {}
    cells: Counter[tuple[str, str, str]] = Counter()
    cell_fields: Counter[tuple[str, str, str]] = Counter()
    field_total = 0

    for form, html in iter_forms(grid):
        html_path = forms_dir / f"{form.form_id}.html"
        html_path.write_text(html, encoding="utf-8")
        html_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

        document = build_answer_key(form)
        problems = validate_answer_key(document)
        if problems:
            raise AssertionError(
                f"{form.form_id}: the generator produced an invalid answer key: "
                + "; ".join(problems)
            )
        key_sha = write_json(keys_dir / f"{form.form_id}.json", document)

        forms.append(form)
        documents.append(document)
        per_form[form.form_id] = {
            "family": form.family.value,
            "template_id": form.template_id,
            "locale": form.locale,
            "tier": form.tier.value,
            "variant": form.variant,
            "field_count": len(form.fields),
            "html_sha256": html_sha,
            "answer_key_sha256": key_sha,
        }
        key = (form.family.value, form.locale, form.tier.value)
        cells[key] += 1
        cell_fields[key] += len(form.fields)
        field_total += len(form.fields)

    split_document = build_split(grid, forms)
    write_json(out / "split.json", split_document)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": grid.seed,
        "base_year": grid.base_year,
        "grid": {
            "families": [family.value for family in grid.families],
            "locales": list(grid.locales),
            "tiers": [tier.value for tier in grid.tiers],
            "templates": list(grid.template_ids()),
            "variants": grid.variants,
        },
        "cells": [
            {
                "family": family,
                "locale": locale,
                "tier": tier,
                "forms": cells[(family, locale, tier)],
                "fields": cell_fields[(family, locale, tier)],
            }
            for family, locale, tier in sorted(cells)
        ],
        "form_count": len(forms),
        "field_count": field_total,
        "forms": per_form,
        "label_coverage": label_coverage(documents),
        "split_sha256": split_sha256(split_document),
    }
    manifest_sha = write_json(out / "manifest.json", manifest)
    return WriteResult(manifest, split_document, manifest_sha, len(forms))


def labels_in_keys(keys: Sequence[dict[str, Any]]) -> set[Label]:
    """Return the set of labels emitted by a collection of answer keys."""
    return {Label(entry["label"]) for document in keys for entry in document["fields"]}
