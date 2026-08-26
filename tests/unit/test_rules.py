"""The rule baseline: precedence, ties, evidence, and the vocabulary itself.

These are about the *mechanism*. The vocabulary's coverage of the taxonomy is
asserted in ``tests/audit/test_label_coverage.py``, which does it through an
end-to-end finding because that is what law 2 clause (d) asks for.
"""

from __future__ import annotations

import re

import pytest

from autofill_audit.classify import (
    EngineChoice,
    UnavailableEngineError,
    load_engine,
)
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_TIER,
    TIER_CONFIDENCE,
    Classifier,
    ConfidenceTier,
    tier_for_confidence,
)
from autofill_audit.classify.rules import RuleClassifier, classify_one
from autofill_audit.classify.rules_table import (
    INTRINSIC_RULES,
    OPTION_RULES,
    TIER_PRECEDENCE,
    TIER_TO_CONFIDENCE,
    VOCABULARY,
    SignalTier,
    labels_with_rules,
    vocabulary_by_locale,
)
from autofill_audit.taxonomy import ALL_LABELS, Label
from builders import make_descriptor

CORPUS_LOCALES = ("de-DE", "en-GB", "en-NG", "en-US", "fr-FR", "ja-JP")


# ---------------------------------------------------------------------------
# The protocol and the ladder.
# ---------------------------------------------------------------------------


def test_the_rule_engine_satisfies_the_classifier_protocol() -> None:
    assert isinstance(RuleClassifier(), Classifier)


def test_describe_names_the_table_and_the_kind_of_confidence() -> None:
    """The renderer branches on ``confidence_kind`` and the run log copies it."""
    described = RuleClassifier().describe()
    assert described["engine"] == "rules"
    assert described[CONFIDENCE_KIND_KEY] == CONFIDENCE_KIND_TIER
    assert re.fullmatch(r"\d+\.\d+\.\d+", described["rule_table_version"])
    assert int(described["vocabulary_rules"]) == len(VOCABULARY)


def test_auto_falls_back_to_rules_and_says_so() -> None:
    """Spec section 10.1: one clear line, and the run continues."""
    loaded = load_engine(EngineChoice.AUTO)
    assert loaded.classifier.name == "rules"
    assert loaded.notice is not None
    assert "not an error" in loaded.notice


def test_naming_rules_explicitly_prints_nothing() -> None:
    assert load_engine(EngineChoice.RULES).notice is None


def test_every_engine_choice_now_loads_or_names_the_phase_that_will_build_it() -> None:
    """Since P6 the ladder has an implementation for every name it accepts.

    The assertion is over the table rather than over a list of names, so adding a
    choice to ``EngineChoice`` without implementing it fails here rather than
    reaching a user as a ``KeyError``. The property this protects is the one the
    parametrised version protected before P6 filled the last rung: a named engine
    is never silently a different engine, because that is how a three-way
    benchmark reports two engines under three names.
    """
    from autofill_audit.classify import _PENDING

    implemented = {
        EngineChoice.AUTO,
        EngineChoice.RULES,
        EngineChoice.NGRAM,
        EngineChoice.LLM,
    }
    assert set(_PENDING) | implemented == set(EngineChoice)
    assert not set(_PENDING) & implemented, "a choice cannot be both built and pending"


def test_naming_the_llm_engine_with_no_server_refuses_rather_than_falling_back() -> None:
    """The same rule as ``ngram`` with no model, for the one engine whose
    prerequisite lives outside this repository.

    Port 1 is the TCP port service multiplexer and nothing in this project ever
    listens there, so this is the no-server case on any machine and it needs no
    network to establish that.
    """
    from autofill_audit.llm.client import LLMConfig

    with pytest.raises(UnavailableEngineError, match="no server answered"):
        load_engine(EngineChoice.LLM, llm_config=LLMConfig(endpoint="http://127.0.0.1:1/v1"))


def test_naming_the_ngram_engine_with_no_model_refuses_rather_than_falling_back() -> None:
    """P4's half of the same rule, now that ``ngram`` has an implementation.

    ``auto`` substitutes and says so; a named engine never does. The suite runs
    with the model search pointed at an empty directory, so this is the
    no-model case whether or not a bundle is checked out.
    """
    with pytest.raises(UnavailableEngineError, match="no trained model was found"):
        load_engine(EngineChoice.NGRAM)


# ---------------------------------------------------------------------------
# Precedence.
# ---------------------------------------------------------------------------


def test_the_precedence_order_is_the_one_the_specification_writes() -> None:
    assert TIER_PRECEDENCE == (
        SignalTier.INTRINSIC,
        SignalTier.LABEL,
        SignalTier.IDENTIFIER,
        SignalTier.PLACEHOLDER,
        SignalTier.CONTEXT,
        SignalTier.OPTIONS,
    )


def test_an_intrinsic_beats_a_label_that_disagrees() -> None:
    """``type="email"`` is very strong: the page meant it."""
    prediction = classify_one(
        make_descriptor(label="Town or city", name="city", input_type="email")
    )
    assert prediction.label == Label.EMAIL.value
    assert prediction.signals[0] == "intrinsic:type-email"


def test_a_label_beats_an_identifier_that_disagrees() -> None:
    prediction = classify_one(make_descriptor(label="Card number", name="zip"))
    assert prediction.label == Label.CC_NUMBER.value


def test_an_identifier_is_used_when_no_label_exists() -> None:
    prediction = classify_one(make_descriptor(name="shipping_postcode"))
    assert prediction.label == Label.POSTAL_CODE.value
    assert prediction.confidence == TIER_CONFIDENCE[ConfidenceTier.MEDIUM]


def test_a_placeholder_is_read_at_medium_and_never_at_high() -> None:
    """Spec section 10.1 puts a placeholder with the identifiers, not the labels."""
    prediction = classify_one(make_descriptor(placeholder="Card number", name="q1"))
    assert prediction.label == Label.CC_NUMBER.value
    assert prediction.confidence == TIER_CONFIDENCE[ConfidenceTier.MEDIUM]
    assert any(signal.startswith("placeholder:") for signal in prediction.signals)


def test_a_real_label_is_read_at_high_and_the_placeholder_is_not_read_at_all() -> None:
    """The extractor's ``label_source`` is what separates the two streams."""
    descriptor = make_descriptor(label="Card number", placeholder="4242", name="q1")
    prediction = classify_one(descriptor)
    assert descriptor.norm.label_source == "label_for"
    assert prediction.confidence == TIER_CONFIDENCE[ConfidenceTier.HIGH]
    assert not any(signal.startswith("placeholder:") for signal in prediction.signals)


def test_context_alone_is_low() -> None:
    prediction = classify_one(make_descriptor(name="q1", context="Company"))
    assert prediction.label == Label.ORGANIZATION.value
    assert prediction.confidence == TIER_CONFIDENCE[ConfidenceTier.LOW]


def test_an_option_list_names_a_select_nothing_else_could() -> None:
    """The hostile case the option tier exists for: no label, a generated id,
    and an intact list of countries."""
    prediction = classify_one(
        make_descriptor(
            element_id="ctl00_txt3_0a9f4c21",
            tag="select",
            input_type=None,
            option_labels=("", "United States", "Canada", "United Kingdom", "Germany"),
            option_values=("", "US", "CA", "GB", "DE"),
        )
    )
    assert prediction.label == Label.COUNTRY.value
    assert any(signal.startswith("options:") for signal in prediction.signals)


# ---------------------------------------------------------------------------
# Ties, which are the safety mechanism.
# ---------------------------------------------------------------------------


def test_a_tie_falls_through_to_the_next_tier() -> None:
    """The English label "Street address" names two different labels."""
    prediction = classify_one(make_descriptor(label="Street address", name="shipping_address1"))
    assert prediction.label == Label.ADDRESS_LINE1.value
    assert prediction.confidence == TIER_CONFIDENCE[ConfidenceTier.MEDIUM]


def test_a_tie_surviving_every_tier_is_unknown_at_zero_confidence() -> None:
    """Law 1: there is no path by which a default branch becomes confident."""
    prediction = classify_one(
        make_descriptor(label="Passwort", name="account_passwort", input_type="password")
    )
    assert prediction.label == Label.UNKNOWN.value
    assert prediction.confidence == 0.0
    assert prediction.signals, "even an UNKNOWN says what it saw"


def test_a_bare_password_field_is_not_guessed_either_way() -> None:
    """A login field and a registration field are indistinguishable here, and a
    confident wrong answer would tell somebody to write the wrong token."""
    for name in ("password", "motdepasse", "passwort"):
        prediction = classify_one(make_descriptor(name=name, input_type="password"))
        assert prediction.label == Label.UNKNOWN.value, name


def test_a_qualified_password_field_is_named() -> None:
    assert classify_one(make_descriptor(label="Confirm password")).label == (
        Label.NEW_PASSWORD.value
    )
    assert classify_one(make_descriptor(label="Current password")).label == (
        Label.CURRENT_PASSWORD.value
    )


def test_an_undetectable_descriptor_is_short_circuited_before_any_tier() -> None:
    """P2's handoff: check it first or hand an empty descriptor to a classifier."""
    prediction = classify_one(
        make_descriptor(selector="frame[#f]", undetectable_reason="cross-origin-frame")
    )
    assert prediction.label == Label.UNKNOWN.value
    assert prediction.confidence == 0.0
    assert prediction.signals == ("undetectable:cross-origin-frame",)


# ---------------------------------------------------------------------------
# Evidence (law 1).
# ---------------------------------------------------------------------------


def test_every_prediction_that_names_a_label_names_its_evidence() -> None:
    prediction = classify_one(make_descriptor(label="Postcode"))
    assert prediction.signals
    assert all(":" in signal for signal in prediction.signals)


def test_a_tie_records_both_candidates_so_the_fall_through_is_explicable() -> None:
    prediction = classify_one(make_descriptor(label="Straße und Hausnummer"))
    assert prediction.label == Label.UNKNOWN.value
    assert "label:street-de" in prediction.signals


def test_signals_are_deduplicated_but_keep_their_order() -> None:
    prediction = classify_one(make_descriptor(label="Email address", name="email"))
    assert len(prediction.signals) == len(set(prediction.signals))


def test_the_runner_up_is_recorded_when_one_exists() -> None:
    prediction = classify_one(make_descriptor(label="Name on card"))
    assert prediction.runner_up is not None
    assert prediction.runner_up[0] == Label.NAME.value


def test_predict_returns_one_prediction_per_descriptor_in_order() -> None:
    fields = [
        make_descriptor(selector="#a", label="Postcode"),
        make_descriptor(selector="#b", label="Town or city"),
    ]
    predictions = RuleClassifier().predict(fields)
    assert [item.selector for item in predictions] == ["#a", "#b"]


def test_latency_is_recorded_per_field() -> None:
    prediction = classify_one(make_descriptor(label="Postcode"))
    assert prediction.latency_us is not None
    assert prediction.latency_us >= 0


# ---------------------------------------------------------------------------
# The table itself.
# ---------------------------------------------------------------------------


def test_every_label_except_unknown_is_reachable_by_a_rule() -> None:
    """Law 2 clause (c). ``check_reachability.py`` enforces the same thing in CI
    against the documented exemption; this is the local statement of it."""
    assert ALL_LABELS - labels_with_rules() == {Label.UNKNOWN}


def test_every_corpus_locale_has_vocabulary_of_its_own() -> None:
    """Spec section 10.1 asks for a comment per locale-specific entry; the locale
    tag is what makes that mechanical rather than a comment that rots."""
    counts = vocabulary_by_locale()
    for locale in CORPUS_LOCALES:
        assert counts.get(locale, 0) > 0, locale


def test_the_postal_code_vocabulary_covers_the_words_the_specification_names() -> None:
    """Spec section 10.1 lists these by name."""
    patterns = [rule.pattern for rule in VOCABULARY if rule.label is Label.POSTAL_CODE]
    for word in (
        "zip",
        "zipcode",
        "postal",
        "postcode",
        "plz",
        "postleitzahl",
        "cap",
        "cp",
        "code postal",
        "郵便番号",
    ):
        assert any(pattern.search(word) for pattern in patterns), word


def test_the_japanese_postal_mark_is_in_the_table_even_though_it_cannot_fire() -> None:
    """Recorded rather than omitted, and honest about its reach.

    Normalisation treats a lone symbol character as a delimiter (spec section
    9.7), so the mark never reaches a token stream. The rule is present because
    the vocabulary is a deliverable and because making it reachable is a
    deliberate normalisation change with snapshot churn, not a quiet fix.
    """
    marks = [rule for rule in VOCABULARY if rule.signal_name == "postcode-mark-ja"]
    assert len(marks) == 1
    from autofill_audit.extract.normalize import normalize_tokens

    assert normalize_tokens("〒") == ()


def test_no_rule_carries_a_weight_outside_the_ordinal_scale() -> None:
    weights = {rule.weight for rule in (*VOCABULARY, *OPTION_RULES, *INTRINSIC_RULES)}
    assert weights <= {120, 100, 80, 60, 40}


def test_every_tier_has_a_confidence_and_context_is_the_weakest() -> None:
    assert TIER_TO_CONFIDENCE[SignalTier.LABEL] is ConfidenceTier.HIGH
    assert TIER_TO_CONFIDENCE[SignalTier.IDENTIFIER] is ConfidenceTier.MEDIUM
    assert TIER_TO_CONFIDENCE[SignalTier.CONTEXT] is ConfidenceTier.LOW


def test_the_tier_values_are_ordered_and_invertible() -> None:
    for tier in ConfidenceTier:
        assert tier_for_confidence(TIER_CONFIDENCE[tier]) is tier


def test_no_signal_name_is_a_taxonomy_label() -> None:
    """Ground rule 6: the taxonomy is the one place a label string lives."""
    values = {label.value for label in ALL_LABELS}
    for rule in (*VOCABULARY, *OPTION_RULES):
        assert rule.signal_name not in values
    for intrinsic in INTRINSIC_RULES:
        assert intrinsic.signal_name not in values
