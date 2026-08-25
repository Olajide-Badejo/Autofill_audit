"""``corpus validate`` over a real corpus, and each way it is meant to fail.

Generation asserts its invariants in memory. These tests exercise the different
question: whether what reached the disk is still coherent. Each check is broken
deliberately, because a validator that has only ever been observed green is
indistinguishable from one that always returns green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autofill_audit.corpus.generator import grid_from
from autofill_audit.corpus.manifest import write_corpus
from autofill_audit.corpus.validate import load_keys, validate_corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A complete but narrow corpus: every family, two locales, every tier.

    Every family, because clause (b) is one of the checks under test and a
    corpus missing a family cannot emit every label. Two locales, one of them
    the held-out one, because the split rules are the other checks under test.
    """
    grid = grid_from(seed=20260825, locales=["en-US", "fr-FR"], base_year=2026)
    write_corpus(grid, tmp_path / "corpus")
    return tmp_path / "corpus"


@pytest.fixture
def partial_corpus(tmp_path: Path) -> Path:
    """A corpus that cannot emit every label, for the clause (b) failure path."""
    grid = grid_from(seed=20260825, families=["login"], locales=["en-US"], base_year=2026)
    write_corpus(grid, tmp_path / "partial")
    return tmp_path / "partial"


def _rewrite(path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_a_freshly_generated_corpus_is_green(corpus: Path) -> None:
    report = validate_corpus(corpus)
    assert report.problems == ()
    assert report.ok
    assert report.form_count > 0
    assert report.field_count > 0


def test_the_committed_sample_is_green(sample_corpus: Path) -> None:
    report = validate_corpus(sample_corpus)
    assert report.problems == ()


def test_the_committed_sample_covers_every_label(sample_corpus: Path) -> None:
    assert validate_corpus(sample_corpus).missing_labels() == []


def test_a_missing_directory_is_reported(tmp_path: Path) -> None:
    report = validate_corpus(tmp_path / "nothing")
    assert not report.ok
    assert "no answer_keys directory" in report.problems[0]


def test_a_broken_selector_is_caught(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    _rewrite(
        corpus / "answer_keys" / f"{form_id}.json",
        lambda document: document["fields"][0].__setitem__("selector", "#not-there"),
    )
    report = validate_corpus(corpus)
    assert any("resolved to 0 elements" in problem for problem in report.problems)


def test_an_edited_form_file_is_caught(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    path = corpus / "forms" / f"{form_id}.html"
    path.write_text(path.read_text(encoding="utf-8") + "<!-- edited -->", encoding="utf-8")
    report = validate_corpus(corpus)
    assert any("does not match its manifest sha" in problem for problem in report.problems)


def test_a_deleted_form_file_is_caught(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    (corpus / "forms" / f"{form_id}.html").unlink()
    report = validate_corpus(corpus)
    assert any("no form file" in problem for problem in report.problems)


def test_a_key_missing_from_the_manifest_is_caught(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    _rewrite(
        corpus / "manifest.json",
        lambda document: document["forms"].pop(form_id),
    )
    report = validate_corpus(corpus)
    assert any("not in the manifest" in problem for problem in report.problems)


def test_a_missing_manifest_is_caught(corpus: Path) -> None:
    (corpus / "manifest.json").unlink()
    report = validate_corpus(corpus)
    assert any("manifest.json is missing" in problem for problem in report.problems)


def test_a_missing_split_is_caught(corpus: Path) -> None:
    (corpus / "split.json").unlink()
    report = validate_corpus(corpus)
    assert any("split.json is missing" in problem for problem in report.problems)


def test_a_field_count_disagreement_is_caught(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    _rewrite(
        corpus / "manifest.json",
        lambda document: document["forms"][form_id].__setitem__("field_count", 999),
    )
    report = validate_corpus(corpus)
    assert any("field count disagrees" in problem for problem in report.problems)


def test_a_leaked_held_out_locale_is_caught(corpus: Path) -> None:
    """The split rule that matters most, broken on purpose."""
    split = json.loads((corpus / "split.json").read_text(encoding="utf-8"))
    target = next(form_id for form_id in split["form_partitions"] if "fr-FR" in form_id)
    split["form_partitions"][target] = "train"
    (corpus / "split.json").write_text(
        json.dumps(split, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = validate_corpus(corpus)
    assert any("must not appear in train" in problem for problem in report.problems)


def test_a_template_in_two_partitions_is_caught(corpus: Path) -> None:
    split = json.loads((corpus / "split.json").read_text(encoding="utf-8"))
    ids = sorted(split["form_partitions"])
    first = ids[0]
    document = json.loads((corpus / "answer_keys" / f"{first}.json").read_text("utf-8"))
    template_id = document["template_id"]
    siblings = [
        form_id
        for form_id in ids
        if json.loads((corpus / "answer_keys" / f"{form_id}.json").read_text("utf-8"))[
            "template_id"
        ]
        == template_id
    ]
    current = split["template_partitions"][template_id]
    other = "dev" if current != "dev" else "test"
    split["form_partitions"][siblings[0]] = other
    (corpus / "split.json").write_text(
        json.dumps(split, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = validate_corpus(corpus)
    assert any(
        "disagrees with its template" in problem or "more than one partition" in problem
        for problem in report.problems
    )


def test_a_missing_split_assignment_is_caught(corpus: Path) -> None:
    split = json.loads((corpus / "split.json").read_text(encoding="utf-8"))
    dropped = sorted(split["form_partitions"])[0]
    del split["form_partitions"][dropped]
    (corpus / "split.json").write_text(
        json.dumps(split, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = validate_corpus(corpus)
    assert any("no split assignment" in problem for problem in report.problems)


def test_an_unknown_partition_is_caught(corpus: Path) -> None:
    split = json.loads((corpus / "split.json").read_text(encoding="utf-8"))
    target = sorted(split["form_partitions"])[0]
    split["form_partitions"][target] = "holdout"
    (corpus / "split.json").write_text(
        json.dumps(split, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = validate_corpus(corpus)
    assert any("unknown partition" in problem for problem in report.problems)


def test_a_missing_label_is_caught(partial_corpus: Path) -> None:
    """A login-only corpus cannot emit the address labels, and validate has to
    say so rather than passing a corpus that could not train a model."""
    report = validate_corpus(partial_corpus)
    assert any("law 2 clause (b)" in problem for problem in report.problems)
    assert "street-address" in report.missing_labels()


def test_an_invalid_key_is_reported_and_skipped(corpus: Path) -> None:
    form_id, _ = next(iter(load_keys(corpus)))
    _rewrite(
        corpus / "answer_keys" / f"{form_id}.json",
        lambda document: document.__setitem__("locale", "xx-XX"),
    )
    report = validate_corpus(corpus)
    assert any(form_id in problem for problem in report.problems)


def test_a_broken_shadow_host_is_caught(corpus: Path) -> None:
    target = None
    for form_id, document in load_keys(corpus):
        if document["page_notes"]["shadow_hosts"]:
            target = form_id
            break
    assert target is not None

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        for entry in document["fields"]:
            if entry["provenance"]["delivery"] == "shadow":
                entry["provenance"]["shadow_host"] = "ce-999"
        document["page_notes"]["shadow_hosts"] = ["ce-999"]

    _rewrite(corpus / "answer_keys" / f"{target}.json", mutate)
    report = validate_corpus(corpus)
    assert any("shadow host" in problem for problem in report.problems)


def test_a_broken_injection_slot_is_caught(corpus: Path) -> None:
    target = None
    for form_id, document in load_keys(corpus):
        if document["page_notes"]["injected_selectors"]:
            target = form_id
            break
    assert target is not None

    def mutate(document: dict) -> None:  # type: ignore[type-arg]
        for entry in document["fields"]:
            if entry["provenance"]["delivery"] == "injected":
                entry["provenance"]["injection_slot"] = "inj-slot-999"

    _rewrite(corpus / "answer_keys" / f"{target}.json", mutate)
    report = validate_corpus(corpus)
    assert any("injection slot" in problem for problem in report.problems)
