"""The prompt contract of spec section 12.2: pruning, versioning, and the schema."""

from __future__ import annotations

import json

import pytest

from autofill_audit.descriptors import GroupRole
from autofill_audit.llm import prompts
from autofill_audit.taxonomy import ALL_LABELS, Label
from builders import make_descriptor

PINNED_FINGERPRINT = "0691c3d4b5d7b60f05d48958792ccf9866863d6b4769c6b119d7954056d2483a"
"""The sha256 of the assembled system prompt and schema at PROMPT_VERSION 1.0.0.

Pinned so that editing the prompt without bumping ``PROMPT_VERSION`` fails here
rather than silently making two runs incomparable under one version. It is the
same mechanism as the golden report snapshots of spec section 15 layer 3, for the
same reason: a change that should be deliberate is made unmissable.

**If this test fails, the prompt changed.** Bump ``PROMPT_VERSION``, update this
literal, and put the change in the CHANGELOG. Do not update the literal alone.
"""


def test_the_prompt_fingerprint_is_the_committed_one() -> None:
    assert prompts.prompt_fingerprint() == PINNED_FINGERPRINT, (
        "the prompt or the schema changed. Bump PROMPT_VERSION and the CHANGELOG "
        "with it: a prompt change is this engine's equivalent of a model sha."
    )


def test_the_version_is_recorded_and_non_empty() -> None:
    assert prompts.PROMPT_VERSION


# ---------------------------------------------------------------------------
# The schema (spec section 12.2).
# ---------------------------------------------------------------------------


def test_the_label_enum_is_the_taxonomy_and_not_a_copy_of_it() -> None:
    """Ground rule 6. A hand-written enum would be a second definition of the
    taxonomy, and the first label added under spec section 7.3 would make the two
    disagree with nothing to notice it."""
    enum = prompts.response_schema()["properties"]["fields"]["items"]["properties"]["label"]["enum"]
    assert set(enum) == {label.value for label in ALL_LABELS}
    assert enum == sorted(enum), "sorted, so two runs of one build send identical requests"


def test_the_schema_forbids_extra_properties_and_requires_the_three_keys() -> None:
    items = prompts.response_schema()["properties"]["fields"]["items"]
    assert items["additionalProperties"] is False
    assert set(items["required"]) == {"selector", "label", "confidence"}
    assert items["properties"]["confidence"]["minimum"] == 0
    assert items["properties"]["confidence"]["maximum"] == 1


def test_unknown_and_not_autofillable_are_answerable() -> None:
    """The system prompt tells the model not to guess and to decline on a search
    box. Both instructions need an answer the schema permits."""
    enum = prompts.label_enum()
    assert Label.UNKNOWN.value in enum
    assert Label.NOT_AUTOFILLABLE.value in enum


def test_the_system_prompt_carries_the_label_list_and_the_confidence_caveat() -> None:
    text = prompts.system_prompt()
    assert Label.ONE_TIME_CODE.value in text
    assert "self-reported" in text
    assert "never treated as a calibrated probability" in text
    assert "copied exactly" in text


# ---------------------------------------------------------------------------
# Pruning: the three drops of spec section 12.2.
# ---------------------------------------------------------------------------


def test_the_declared_autocomplete_is_dropped() -> None:
    """The drop spec section 12.2 calls required. Leaving it in would make every
    clean-tier number a measure of copying."""
    declared = make_descriptor(selector="#a", label="First name", declared="given-name")
    undeclared = make_descriptor(selector="#a", label="First name")

    assert prompts.prune(declared) == prompts.prune(undeclared)
    assert "given-name" not in json.dumps(prompts.prune(declared))


def test_geometry_is_dropped() -> None:
    from dataclasses import replace

    field = make_descriptor(selector="#a", label="First name")
    with_box = replace(field, bbox=(10.0, 20.0, 100.0, 30.0))

    assert prompts.prune(with_box) == prompts.prune(field)


def test_framework_attributes_are_dropped() -> None:
    from dataclasses import replace

    field = make_descriptor(selector="#a", label="First name")
    with_attrs = replace(field, framework_attrs=(("ng-model", "user.firstName"),))

    assert prompts.prune(with_attrs) == prompts.prune(field)
    assert "ng-model" not in json.dumps(prompts.prune(with_attrs))


def test_declaration_independence_is_checked_over_a_whole_page() -> None:
    fields = [
        make_descriptor(selector="#a", label="First name", declared="given-name"),
        make_descriptor(selector="#b", label="Postal code", declared="postal-code"),
    ]
    prompts.assert_no_declaration_leaks(prompts.prune_all(fields), fields)


def test_a_leak_is_caught_rather_than_trusted() -> None:
    field = make_descriptor(selector="#a", label="First name", declared="given-name")
    leaked = [dict(prompts.prune(field), autocomplete="given-name")]
    with pytest.raises(ValueError, match="changed the pruned payload"):
        prompts.assert_no_declaration_leaks(leaked, [field])


def test_a_field_named_after_its_own_label_does_not_trip_the_leak_check() -> None:
    """The check is independence, not a substring search.

    A field named ``email`` that also declares ``autocomplete="email"`` is the
    obvious false positive of the naive implementation, and it is common enough
    in a clean-tier corpus that it would have fired on the first real run.
    """
    field = make_descriptor(selector="#a", label="Email address", name="email", declared="email")
    prompts.assert_no_declaration_leaks([prompts.prune(field)], [field])


# ---------------------------------------------------------------------------
# Pruning: what is kept, and the truncation of spec section 15's hard cases.
# ---------------------------------------------------------------------------


def test_the_signals_the_ngram_featuriser_reads_are_all_kept() -> None:
    """The fairness rule: the language model sees what the featuriser sees.

    Withholding a signal one engine has from the other tilts the comparison
    exactly as far as handing over the whole document would.
    """
    field = make_descriptor(
        selector="form#co >>> #f7",
        label="Postal code",
        name="plz",
        element_id="f7",
        css_classes=("form-control", "postal"),
        tag="input",
        input_type="text",
        inputmode="numeric",
        maxlength=5,
        option_labels=(),
        group_role=GroupRole.NONE,
        document_index=7,
    )
    pruned = prompts.prune(field)

    assert pruned["selector"] == "form#co >>> #f7"
    assert pruned["tag"] == "input"
    assert pruned["type"] == "text"
    assert pruned["inputmode"] == "numeric"
    assert pruned["maxlength"] == 5
    assert pruned["name"] == "plz"
    assert pruned["id"] == "f7"
    assert pruned["classes"] == ["form-control", "postal"]
    assert pruned["position"] == 7
    assert pruned["text"]["label"] == "Postal code"


def test_absent_signals_are_omitted_rather_than_sent_as_null() -> None:
    """Thirty controls each carrying nine nulls is most of a context window spent
    on the word null."""
    field = make_descriptor(selector="#a", label="First name")
    pruned = prompts.prune(field)

    assert None not in pruned.values()
    assert "aria_label" not in pruned["text"]


def test_a_ten_thousand_character_label_is_truncated() -> None:
    field = make_descriptor(selector="#a", label="x" * 10_000)
    pruned = prompts.prune(field)

    assert len(pruned["text"]["label"]) == prompts.TEXT_MAX_CHARS


def test_five_thousand_options_are_truncated_and_the_count_survives() -> None:
    """Spec section 15's hard case. The truncation must not lose the fact that the
    control had five thousand options, because that fact is itself a signal."""
    field = make_descriptor(
        selector="#a",
        label="Country",
        tag="select",
        input_type=None,
        option_labels=tuple(f"Option {index}" for index in range(5000)),
    )
    pruned = prompts.prune(field)

    assert len(pruned["option_labels"]) == prompts.OPTION_LABEL_LIMIT
    assert pruned["option_count"] == 5000


def test_a_month_list_survives_truncation_intact() -> None:
    """Twelve rather than ten, because a month list cut at ten loses the shape
    that identifies it."""
    months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    field = make_descriptor(
        selector="#a", label="Month", tag="select", input_type=None, option_labels=months
    )
    pruned = prompts.prune(field)

    assert pruned["option_labels"] == list(months)


def test_the_user_message_is_the_pruned_array_and_nothing_else() -> None:
    fields = [make_descriptor(selector="#a", label="First name")]
    message = prompts.user_message(prompts.prune_all(fields))

    parsed = json.loads(message)
    assert isinstance(parsed, list)
    assert parsed[0]["selector"] == "#a"


def test_the_semantic_retry_names_the_selectors_rather_than_counting_them() -> None:
    """ "Your answer was wrong" is not a correction and a model given it produces
    the same answer."""
    message = prompts.semantic_retry_message(["#missing"], ["#invented"])

    assert "#missing" in message
    assert "#invented" in message
    assert "omitted 1 selector" in message
    assert "invented 1 selector" in message


def test_the_parse_retry_carries_the_parser_error() -> None:
    message = prompts.parse_retry_message("Expecting value: line 1 column 1")

    assert "Expecting value: line 1 column 1" in message
    assert "no code fence" in message
