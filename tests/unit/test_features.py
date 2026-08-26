"""Feature extraction: the analysers, the fitted space, and the two properties.

Two of these tests are load bearing beyond their own assertion.

``test_char_analyser_agrees_with_scikit_learn`` is the reason this project is
allowed to claim that its hand-rolled analyser reproduces ``char_wb``. The claim
is in the module docstring of ``classify/features.py`` and in the model card, and
an unchecked claim of that shape is exactly the train/serve skew spec section
10.2 warns about, arriving by a different door.

``test_featurization_is_order_independent`` is spec section 15 layer 4's
featurisation property. It is asserted over a batch rather than over one
descriptor because the failure it guards against is a featuriser that reads its
neighbours, and one descriptor cannot exhibit that.
"""

from __future__ import annotations

import json
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.builders import make_descriptor

from autofill_audit.classify.features import (
    BLOCK_CHAR,
    BLOCK_OPTION,
    BLOCK_STRUCTURAL,
    BLOCK_WORD,
    FeatureConfig,
    FeatureSpace,
    FeatureSpaceError,
    char_wb_ngrams,
    descriptor_features,
    featurize,
    fit_feature_space,
    option_tokens,
    signal_name,
    word_ngrams,
)
from autofill_audit.descriptors import FieldDescriptor, GroupRole
from autofill_audit.taxonomy import ALL_LABELS

CONFIG = FeatureConfig()


# ---------------------------------------------------------------------------
# The analysers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "a",
        "ab",
        "abc",
        "zip",
        "L:postal L:code I:zipcode",
        "L:postleitzahl C:lieferadresse",
        "L:郵便番号 I:yubin",
        "  spaced   out  words ",
        "L:x I:yy C:zzz",
    ],
)
def test_char_analyser_agrees_with_scikit_learn(text: str) -> None:
    """The hand-rolled char_wb enumeration is scikit-learn's, exactly.

    Including the short-word rule: a word shorter than n yields its padded self
    once rather than once per n. That single ``break`` is the whole difference
    between a faithful reimplementation and one that quietly triples the weight
    of every two letter token.
    """
    sklearn_text = pytest.importorskip("sklearn.feature_extraction.text")
    analyser = sklearn_text.CountVectorizer(
        analyzer="char_wb",
        ngram_range=(CONFIG.char_min_n, CONFIG.char_max_n),
        # The blob arrives already casefolded by the extractor, and its stream
        # prefixes are uppercase on purpose. Lowercasing here would compare this
        # module against a scikit-learn that had been told to destroy the one
        # signal the blob exists to carry.
        lowercase=False,
    ).build_analyzer()
    assert char_wb_ngrams(text, CONFIG.char_min_n, CONFIG.char_max_n) == analyser(text)


def test_word_analyser_keeps_the_stream_prefix() -> None:
    """A blob token carries the stream it came from, and the analyser keeps it."""
    grams = word_ngrams("L:postal L:code I:zip", 1, 2)
    assert "L:postal" in grams
    assert "L:postal L:code" in grams
    assert "L:code I:zip" in grams
    assert "postal" not in grams


def test_word_analyser_emits_no_bigram_from_one_word() -> None:
    """A single token has no bigram, and the range still yields its unigram."""
    assert word_ngrams("L:zip", 1, 2) == ["L:zip"]


# ---------------------------------------------------------------------------
# The indicator blocks.
# ---------------------------------------------------------------------------


def test_option_shape_recognises_months_and_years() -> None:
    """A month select and a year select are told apart by their numbers."""
    months = make_descriptor(
        "#m",
        tag="select",
        input_type=None,
        option_labels=tuple(f"{n:02d}" for n in range(1, 13)),
        option_values=tuple(str(n) for n in range(1, 13)),
    )
    years = make_descriptor(
        "#y",
        tag="select",
        input_type=None,
        option_labels=tuple(str(year) for year in range(2026, 2036)),
        option_values=tuple(str(year) for year in range(2026, 2036)),
    )
    month_names = set(descriptor_features(months, CONFIG))
    year_names = set(descriptor_features(years, CONFIG))
    assert f"{BLOCK_OPTION}:months" in month_names
    assert f"{BLOCK_OPTION}:months" not in year_names
    assert f"{BLOCK_OPTION}:years" in year_names
    assert f"{BLOCK_OPTION}:years" not in month_names


def test_option_shape_recognises_a_country_list() -> None:
    """A long list of two letter codes is a country select whatever it says."""
    codes = tuple(f"{chr(a)}{chr(b)}" for a in range(65, 70) for b in range(65, 75))
    countries = make_descriptor(
        "#c",
        tag="select",
        input_type=None,
        option_labels=codes,
        option_values=codes,
    )
    assert f"{BLOCK_OPTION}:countries" in descriptor_features(countries, CONFIG)


def test_option_shape_recognises_a_short_enumeration() -> None:
    """Two or three options is a different kind of control from fifty."""
    short = make_descriptor(
        "#s",
        tag="select",
        input_type=None,
        option_labels=("Mr", "Mrs", "Dr"),
        option_values=("mr", "mrs", "dr"),
    )
    names = descriptor_features(short, CONFIG)
    assert f"{BLOCK_OPTION}:shortenum" in names
    assert f"{BLOCK_OPTION}:countries" not in names


def test_a_text_input_has_no_option_features() -> None:
    """A control with no options contributes nothing from block four."""
    names = descriptor_features(make_descriptor("#t", label="Postcode"), CONFIG)
    assert not [name for name in names if name.startswith(f"{BLOCK_OPTION}:")]


def test_structural_features_name_where_the_control_sits() -> None:
    """Block five reads the structure, and absence is not silence."""
    names = set(descriptor_features(make_descriptor("#t", document_index=7), CONFIG))
    assert f"{BLOCK_STRUCTURAL}:position=5to7" in names
    assert f"{BLOCK_STRUCTURAL}:inform" in names
    assert f"{BLOCK_STRUCTURAL}:inframe" not in names


def test_group_role_reaches_the_features() -> None:
    """The split-expiry structure is a feature, since no text carries it."""
    names = descriptor_features(
        make_descriptor("#exp", tag="select", input_type=None, group_role=GroupRole.CC_EXP_MONTH),
        CONFIG,
    )
    assert "t:role=cc_exp_month" in names


def test_option_tokens_normalise_once() -> None:
    """Option words go through the extractor's normalisation, not a second one."""
    descriptor = make_descriptor(
        "#c", tag="select", input_type=None, option_labels=("United Kingdom",)
    )
    assert option_tokens(descriptor) == ("united", "kingdom")


# ---------------------------------------------------------------------------
# The fitted space.
# ---------------------------------------------------------------------------


def _training_batch() -> list[FieldDescriptor]:
    """A handful of descriptors with overlapping vocabulary."""
    return [
        make_descriptor("#a", label="Postcode", name="postcode"),
        make_descriptor("#b", label="Post code", name="postal_code"),
        make_descriptor("#c", label="Email", input_type="email", name="email"),
        make_descriptor("#d", label="E-mail address", name="emailAddress"),
        make_descriptor("#e", label="Card number", name="cardnumber", maxlength=19),
    ]


def test_the_document_frequency_floor_drops_a_singleton() -> None:
    """A feature seen on one descriptor only is below the floor and is dropped."""
    batch = _training_batch()
    space = fit_feature_space(batch, CONFIG)
    frequencies: dict[str, int] = {}
    for descriptor in batch:
        for name in descriptor_features(descriptor, CONFIG):
            frequencies[name] = frequencies.get(name, 0) + 1
    singletons = {
        name
        for name, count in frequencies.items()
        if count < CONFIG.char_min_df and name.startswith(f"{BLOCK_CHAR}:")
    }
    assert singletons
    assert not singletons & set(space.names)


def test_the_feature_ceiling_is_applied_and_is_stable() -> None:
    """A ceiling below the observed count keeps a deterministic subset."""
    batch = _training_batch()
    tight = FeatureConfig(char_min_df=1, char_max_features=5, word_min_df=1, word_max_features=3)
    first = fit_feature_space(batch, tight)
    second = fit_feature_space(list(reversed(batch)), tight)
    assert first.names == second.names
    assert len([n for n in first.names if n.startswith(f"{BLOCK_CHAR}:")]) == 5
    assert len([n for n in first.names if n.startswith(f"{BLOCK_WORD}:")]) == 3


def test_the_space_round_trips_through_json() -> None:
    """A committed vocabulary rebuilds into the object that wrote it."""
    space = fit_feature_space(_training_batch(), CONFIG)
    rebuilt = FeatureSpace.from_json(json.loads(json.dumps(space.to_json())))
    assert rebuilt.names == space.names
    assert rebuilt.config == space.config
    assert rebuilt.width == space.width
    assert sum(rebuilt.block_counts().values()) == rebuilt.width


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 99, "config": {}, "names": []},
        {"schema_version": 1, "config": "not an object", "names": []},
        {"schema_version": 1, "config": FeatureConfig().to_json(), "names": "not a list"},
        {"schema_version": 1, "config": FeatureConfig().to_json(), "names": [1]},
        {"schema_version": 1, "config": FeatureConfig().to_json(), "names": ["c:a", "c:a"]},
        {"schema_version": 1, "config": {"char_min_n": "three"}, "names": []},
    ],
)
def test_a_broken_vocabulary_is_refused_by_name(payload: dict[str, object]) -> None:
    """Every malformed shape raises rather than loading a half-built space."""
    with pytest.raises(FeatureSpaceError):
        FeatureSpace.from_json(payload)


def test_featurize_drops_a_feature_the_space_does_not_carry() -> None:
    """An unseen n-gram contributes nothing rather than contributing noise."""
    space = fit_feature_space(_training_batch(), CONFIG)
    unseen = make_descriptor("#z", label="Kanton", name="kanton")
    matrix = featurize([unseen], space)
    assert matrix.shape == (1, space.width)
    for column, _ in matrix.row_items(0):
        assert space.names[column] in space.index


def test_featurize_and_to_dense_agree() -> None:
    """The sparse rows and the dense array the session takes are the same thing."""
    batch = _training_batch()
    space = fit_feature_space(batch, CONFIG)
    matrix = featurize(batch, space)
    dense = matrix.to_dense()
    assert dense.shape == (len(batch), space.width)
    for row in range(matrix.rows):
        for column, value in matrix.row_items(row):
            assert dense[row, column] == pytest.approx(value)


# ---------------------------------------------------------------------------
# The two properties of spec section 15 layer 4.
# ---------------------------------------------------------------------------


def test_featurization_is_deterministic() -> None:
    """The same descriptors twice produce the same matrix, to the byte."""
    batch = _training_batch()
    space = fit_feature_space(batch, CONFIG)
    first = featurize(batch, space)
    second = featurize(batch, space)
    assert first.indptr.tolist() == second.indptr.tolist()
    assert first.indices.tolist() == second.indices.tolist()
    assert first.data.tolist() == second.data.tolist()


@settings(max_examples=40, deadline=None)
@given(
    labels=st.lists(
        st.sampled_from(
            [
                "Postcode",
                "E-mail",
                "Card number",
                "Ville",
                "Straße",
                "郵便番号",
                "Security code",
                "",
            ]
        ),
        min_size=2,
        max_size=6,
    ),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_featurization_is_order_independent(labels: list[str], seed: int) -> None:
    """Featurising a page in any order gives each field the same row.

    The property spec section 15 layer 4 asks for. A featuriser that read a
    neighbour, a running total, or a position derived from the batch would fail
    this and would fail nothing else until a page arrived with its fields in an
    unusual order.
    """
    batch = [
        make_descriptor(f"#f{index}", label=label or None, document_index=index)
        for index, label in enumerate(labels)
    ]
    space = fit_feature_space(batch, FeatureConfig(char_min_df=1, word_min_df=1))
    order = list(range(len(batch)))
    random.Random(seed).shuffle(order)

    straight = featurize(batch, space)
    shuffled = featurize([batch[index] for index in order], space)
    for position, index in enumerate(order):
        assert shuffled.row_items(position) == straight.row_items(index)


# ---------------------------------------------------------------------------
# Evidence naming.
# ---------------------------------------------------------------------------


def test_signal_names_carry_the_block_they_came_from() -> None:
    """Evidence names where it came from, in P3's vocabulary for evidence."""
    assert signal_name("c: pos").startswith("ngram:char:")
    assert signal_name("w:L:postal").startswith("ngram:word:")
    assert signal_name("t:type=email").startswith("ngram:attr:")
    assert signal_name("o:months").startswith("ngram:options:")
    assert signal_name("s:inframe").startswith("ngram:structure:")


def test_no_signal_name_is_a_taxonomy_label() -> None:
    """A feature is named after the feature, never after the class it supports.

    The same assertion P3 makes about the rule engine's signal names, made here
    over every feature a fitted space carries. A signal name that collided with a
    label would make a report's evidence line read as a second, unsourced claim.
    """
    space = fit_feature_space(_training_batch(), FeatureConfig(char_min_df=1, word_min_df=1))
    values = {label.value for label in ALL_LABELS}
    assert not {signal_name(name) for name in space.names} & values
