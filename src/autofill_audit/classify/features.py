"""Feature extraction shared by training and inference (spec section 10.2).

**There is one implementation and both paths import it.** The most common way a
deployed text classifier silently degrades is train/serve feature skew, and the
only reliable defence is one code path plus a parity test. ``scripts/train.py``
calls the functions in this module to build its design matrix, and
``classify/onnx_model.py`` calls the same functions on the descriptors of a live
page. Neither has a featuriser of its own and neither is allowed to grow one.

The five blocks of spec section 10.2, concatenated in this order:

1. Character n-grams over ``norm.text_blob``, word-boundary aware, three to five.
2. Word unigrams and bigrams over the same blob.
3. Categorical one-hots for the intrinsic attributes.
4. Option-shape features for a ``<select>``.
5. Structural features: position, siblings, fieldset, shadow root, frame.

Why this module carries its own analysers
-----------------------------------------

The character and word analysers here are hand-rolled rather than borrowed from
scikit-learn, and that is the pre-decided ONNX route of spec section 10.5 rather
than an accident. A vectorizer inside the exported graph would make the graph's
tokenisation and Python's disagree in ways that only a parity test finds; a
vectorizer outside it would put scikit-learn on the runtime dependency list of a
tool that installs with ``pipx``. Doing the enumeration here in plain Python
costs the vectorizer's C speed and buys an inference path whose only dependencies
are numpy and onnxruntime, and an ONNX graph that holds nothing but a matrix
multiply.

The character analyser reproduces scikit-learn's ``char_wb`` semantics exactly,
including its treatment of a word shorter than the n-gram length, and a test
asserts that agreement against scikit-learn itself. That test is the reason the
reproduction is worth claiming rather than merely intending.

Weighting
---------

Counts, then L2 normalisation **within each text block separately**. The two text
blocks are normalised apart from each other so that a control with a long context
paragraph cannot drown its own label, and the three small blocks are left as
plain indicators so that "this is a select" means the same thing on a field with
two words of text and on a field with forty.

Determinism and order independence
----------------------------------

Every feature of a descriptor is computed from that descriptor alone. Nothing
here reads a neighbour, a batch statistic, or a clock, so featurising a page in
one order and in another produces the same rows in the corresponding places.
Spec section 15 layer 4 requires that as a property test, and the honest way to
pass it is to make it true by construction rather than to sort the output.

The one place this bites is spec section 10.2's "position within form". A
descriptor carries no within-form ordinal, and deriving one by counting the batch
would make a field's features depend on which other fields happened to be passed
alongside it. So the position feature buckets ``document_index``, which the
extractor assigns once per page and which is stable for a given page whatever is
done with it afterwards.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Self

import numpy as np

from autofill_audit.descriptors import FieldDescriptor
from autofill_audit.extract.normalize import normalize_tokens

__all__ = [
    "BLOCK_CATEGORICAL",
    "BLOCK_CHAR",
    "BLOCK_OPTION",
    "BLOCK_STRUCTURAL",
    "BLOCK_WORD",
    "VOCAB_SCHEMA_VERSION",
    "FeatureConfig",
    "FeatureMatrix",
    "FeatureSpace",
    "FeatureSpaceError",
    "char_wb_ngrams",
    "descriptor_features",
    "featurize",
    "fit_feature_space",
    "option_tokens",
    "signal_name",
    "word_ngrams",
]

VOCAB_SCHEMA_VERSION: Final[int] = 1
"""Bumped when a committed ``vocab.json`` stops being readable by this module."""

BLOCK_CHAR: Final[str] = "c"
BLOCK_WORD: Final[str] = "w"
BLOCK_CATEGORICAL: Final[str] = "t"
BLOCK_OPTION: Final[str] = "o"
BLOCK_STRUCTURAL: Final[str] = "s"
"""The five block prefixes. A feature name is ``prefix:detail``, which is what
makes a fitted vocabulary readable and a finding's evidence nameable."""

_SIGNAL_PREFIX: Final[dict[str, str]] = {
    BLOCK_CHAR: "ngram:char",
    BLOCK_WORD: "ngram:word",
    BLOCK_CATEGORICAL: "ngram:attr",
    BLOCK_OPTION: "ngram:options",
    BLOCK_STRUCTURAL: "ngram:structure",
}
"""How a feature name is spelled when it appears in ``Prediction.signals``.

The prefix names where the evidence came from, which is the convention P3
established for the rule engine's six tiers. It deliberately does not reuse
``label:`` or ``identifier:``: those name per-stream rule matches, and a feature
weight is a different kind of claim that would be misread under the same word."""


class FeatureSpaceError(ValueError):
    """A serialised feature space is missing, unreadable, or inconsistent."""


# ---------------------------------------------------------------------------
# Configuration. Fixed at P4 and recorded; never tuned against the test split.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    """The caps of spec section 10.2, fixed at P4 and committed with the model.

    The n-gram range is the specification's decision and is repeated here rather
    than left implicit: two is too short to separate a three letter postcode word
    from noise, six and above explodes the space on a corpus this size, and three
    to five spans a whole short token up to a discriminative fragment of a long
    one. The document-frequency floor and the feature ceiling exist so that the
    committed vocabulary stays something a reviewer can actually read.
    """

    char_min_n: int = 3
    char_max_n: int = 5
    char_min_df: int = 2
    char_max_features: int = 100_000
    word_min_n: int = 1
    word_max_n: int = 2
    word_min_df: int = 2
    word_max_features: int = 50_000

    def to_json(self) -> dict[str, int]:
        """Emit the plain JSON form."""
        return {
            "char_min_n": self.char_min_n,
            "char_max_n": self.char_max_n,
            "char_min_df": self.char_min_df,
            "char_max_features": self.char_max_features,
            "word_min_n": self.word_min_n,
            "word_max_n": self.word_max_n,
            "word_min_df": self.word_min_df,
            "word_max_features": self.word_max_features,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        values: dict[str, int] = {}
        for key in (
            "char_min_n",
            "char_max_n",
            "char_min_df",
            "char_max_features",
            "word_min_n",
            "word_max_n",
            "word_min_df",
            "word_max_features",
        ):
            raw = payload.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise FeatureSpaceError(f"config.{key}: expected an integer, found {raw!r}")
            values[key] = raw
        return cls(**values)


# ---------------------------------------------------------------------------
# Block 1 and block 2: the text analysers.
# ---------------------------------------------------------------------------

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s\s+")


def char_wb_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    """Return the word-boundary aware character n-grams of ``text``.

    This reproduces scikit-learn's ``analyzer="char_wb"`` exactly, padding each
    whitespace separated word with a space on both sides and enumerating within
    that padded word only, so an n-gram never straddles two words. A word shorter
    than ``n`` yields its padded self once rather than once per n, which is the
    detail an independent reimplementation gets wrong and which the unit tests
    assert against scikit-learn.

    Padding is what makes a prefix and a suffix distinguishable from the middle
    of a word: a leading space plus ``pos`` is evidence about a token that starts
    with those letters, where ``pos`` alone is evidence about a token that merely
    contains them.
    """
    normalised = _WHITESPACE.sub(" ", text)
    ngrams: list[str] = []
    for word in normalised.split():
        padded = f" {word} "
        length = len(padded)
        for size in range(min_n, max_n + 1):
            offset = 0
            ngrams.append(padded[offset : offset + size])
            while offset + size < length:
                offset += 1
                ngrams.append(padded[offset : offset + size])
            if offset == 0:
                # The word is shorter than this n, so the whole padded word was
                # emitted once above and every larger n would emit it again.
                break
    return ngrams


def word_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    """Return the word n-grams of ``text``, splitting on whitespace only.

    Whitespace and nothing else, because ``norm.text_blob`` is already a token
    stream: the extractor normalised every source through spec section 9.7 and
    then prefixed each token with the letter naming the stream it came from, for
    the label, identifier, and context streams. A word pattern of the usual kind
    would split those prefixes back off and throw away the one thing the blob
    exists to preserve.

    A bigram joins its members with a single space, so a two token phrase is one
    feature and reads as what it is.
    """
    words = text.split()
    ngrams: list[str] = []
    for size in range(min_n, max_n + 1):
        if size == 1:
            ngrams.extend(words)
            continue
        for start in range(len(words) - size + 1):
            ngrams.append(" ".join(words[start : start + size]))
    return ngrams


# ---------------------------------------------------------------------------
# Blocks 3 to 5: the indicator features.
# ---------------------------------------------------------------------------


def _bucket(value: int, bounds: Sequence[int]) -> str:
    """Return the name of the bucket ``value`` falls in.

    Buckets rather than raw counts because a linear model given a raw count
    learns a slope, and none of these quantities is linear in anything. The
    difference between a select with two options and one with twelve is a change
    of kind; the difference between one with ninety and one with a hundred is
    not.
    """
    previous = 0
    for bound in bounds:
        if value < bound:
            top = bound - 1
            return str(previous) if top <= previous else f"{previous}to{top}"
        previous = bound
    return f"{previous}plus"


_MAXLENGTH_BOUNDS: Final[tuple[int, ...]] = (1, 3, 5, 9, 17, 33, 65)
_OPTION_COUNT_BOUNDS: Final[tuple[int, ...]] = (1, 2, 4, 7, 13, 31, 100)
_POSITION_BOUNDS: Final[tuple[int, ...]] = (1, 2, 3, 5, 8, 12, 20)
_SIBLING_BOUNDS: Final[tuple[int, ...]] = (1, 2, 4, 7, 13, 21)

_MONTH_NUMBERS: Final[frozenset[int]] = frozenset(range(1, 13))
_MIN_YEAR: Final[int] = 1990
_MAX_YEAR: Final[int] = 2100
_MIN_YEAR_RUN: Final[int] = 4
_COUNTRY_LIST_MINIMUM: Final[int] = 40
_COUNTRY_CODE_LENGTH: Final[int] = 2
_SHORT_ENUM_MAXIMUM: Final[int] = 6

_DIGITS: Final[re.Pattern[str]] = re.compile(r"^\d+$")


def _categorical_features(descriptor: FieldDescriptor) -> list[str]:
    """Block 3: the intrinsic attributes as one-hots plus small booleans."""
    names = [
        f"{BLOCK_CATEGORICAL}:tag={descriptor.tag}",
        f"{BLOCK_CATEGORICAL}:type={descriptor.input_type or 'absent'}",
        f"{BLOCK_CATEGORICAL}:inputmode={descriptor.inputmode or 'absent'}",
        f"{BLOCK_CATEGORICAL}:role={descriptor.group_role.value}",
        f"{BLOCK_CATEGORICAL}:maxlength={_maxlength_bucket(descriptor.maxlength)}",
    ]
    if descriptor.required:
        names.append(f"{BLOCK_CATEGORICAL}:required")
    if descriptor.readonly:
        names.append(f"{BLOCK_CATEGORICAL}:readonly")
    if descriptor.pattern:
        names.append(f"{BLOCK_CATEGORICAL}:haspattern")
    return names


def _maxlength_bucket(maxlength: int | None) -> str:
    """The maxlength bucket, with absence as its own value rather than as zero."""
    if maxlength is None:
        return "absent"
    return _bucket(maxlength, _MAXLENGTH_BOUNDS)


def _option_numbers(values: Sequence[str]) -> list[int]:
    """Return the option values that are plain integers, in order."""
    numbers: list[int] = []
    for value in values:
        text = value.strip()
        if _DIGITS.match(text):
            numbers.append(int(text))
    return numbers


def _looks_like_months(labels: Sequence[str], values: Sequence[str]) -> bool:
    """Whether a select offers the twelve months.

    Structural rather than lexical, on purpose. A month list is recognisable
    from its numbers in every locale in the corpus, and a word list would need a
    twelve entry table per language that the rule table already carries for a
    different job. The month names still reach the model through the label and
    context text when they are written beside the control.
    """
    for source in (values, labels):
        numbers = set(_option_numbers(source))
        if numbers >= _MONTH_NUMBERS and len(numbers) <= len(_MONTH_NUMBERS) + 1:
            return True
    return False


def _looks_like_years(labels: Sequence[str], values: Sequence[str]) -> bool:
    """Whether a select offers a run of consecutive plausible years."""
    for source in (values, labels):
        years = sorted({n for n in _option_numbers(source) if _MIN_YEAR <= n <= _MAX_YEAR})
        if len(years) < _MIN_YEAR_RUN:
            continue
        if years[-1] - years[0] == len(years) - 1:
            return True
    return False


def _looks_like_countries(labels: Sequence[str], values: Sequence[str]) -> bool:
    """Whether a select offers a country list.

    Two shapes, either of which is enough: a list long enough that nothing else
    on a form is that long, or a list of two letter codes, which is what a
    country select carries in its values even when its labels are localised.
    """
    if len(labels) >= _COUNTRY_LIST_MINIMUM:
        return True
    codes = [value for value in values if len(value.strip()) == _COUNTRY_CODE_LENGTH]
    return len(values) >= _COUNTRY_LIST_MINIMUM // 2 and len(codes) >= len(values) - 1


def _option_features(descriptor: FieldDescriptor) -> list[str]:
    """Block 4: the shape of a select's option list, never its words.

    Spec section 10.2 puts option *shape* in the feature set and leaves option
    text out of the two text blocks, which are over ``text_blob`` alone. That is
    followed exactly here rather than quietly widened, and the cost is recorded
    in the model card: a hostile select whose only evidence is its option words
    reaches this model as a shape and reaches the rule engine as a vocabulary
    match.
    """
    labels = descriptor.option_labels
    values = descriptor.option_values
    if not labels and not values:
        return []
    names = [f"{BLOCK_OPTION}:count={_bucket(len(labels), _OPTION_COUNT_BOUNDS)}"]
    if _looks_like_months(labels, values):
        names.append(f"{BLOCK_OPTION}:months")
    if _looks_like_years(labels, values):
        names.append(f"{BLOCK_OPTION}:years")
    if _looks_like_countries(labels, values):
        names.append(f"{BLOCK_OPTION}:countries")
    if 0 < len(labels) <= _SHORT_ENUM_MAXIMUM:
        names.append(f"{BLOCK_OPTION}:shortenum")
    return names


def _structural_features(descriptor: FieldDescriptor) -> list[str]:
    """Block 5: where the control sits, rather than what it says."""
    position = _bucket(descriptor.document_index, _POSITION_BOUNDS)
    siblings = _bucket(descriptor.sibling_control_count, _SIBLING_BOUNDS)
    names = [
        f"{BLOCK_STRUCTURAL}:position={position}",
        f"{BLOCK_STRUCTURAL}:siblings={siblings}",
    ]
    if descriptor.form_index is not None:
        names.append(f"{BLOCK_STRUCTURAL}:inform")
    if descriptor.fieldset_index is not None:
        names.append(f"{BLOCK_STRUCTURAL}:infieldset")
    if descriptor.shadow_path:
        names.append(f"{BLOCK_STRUCTURAL}:inshadowroot")
    if descriptor.frame_path:
        names.append(f"{BLOCK_STRUCTURAL}:inframe")
    if not descriptor.is_visible:
        names.append(f"{BLOCK_STRUCTURAL}:hidden")
    return names


# ---------------------------------------------------------------------------
# One descriptor's features.
# ---------------------------------------------------------------------------


def _l2_weighted(counts: Mapping[str, int]) -> dict[str, float]:
    """Return ``counts`` scaled so the block has unit L2 norm."""
    norm = math.sqrt(sum(float(count) * float(count) for count in counts.values()))
    if norm == 0.0:
        return {}
    return {name: float(count) / norm for name, count in counts.items()}


def _tally(names: Iterable[str]) -> dict[str, int]:
    """Count occurrences, preserving first-seen order for readability."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return counts


def descriptor_features(descriptor: FieldDescriptor, config: FeatureConfig) -> dict[str, float]:
    """Return one descriptor's feature name to value mapping.

    This is the whole of the featurisation for one control, and the fitted
    vocabulary is applied afterwards rather than here, so that the same function
    serves the fitting pass (which has no vocabulary yet) and the inference pass
    (which drops anything the vocabulary does not carry).
    """
    features: dict[str, float] = {}

    blob = descriptor.norm.text_blob
    char_counts = _tally(
        f"{BLOCK_CHAR}:{ngram}"
        for ngram in char_wb_ngrams(blob, config.char_min_n, config.char_max_n)
    )
    features.update(_l2_weighted(char_counts))

    word_counts = _tally(
        f"{BLOCK_WORD}:{ngram}" for ngram in word_ngrams(blob, config.word_min_n, config.word_max_n)
    )
    features.update(_l2_weighted(word_counts))

    for name in _categorical_features(descriptor):
        features[name] = 1.0
    for name in _option_features(descriptor):
        features[name] = 1.0
    for name in _structural_features(descriptor):
        features[name] = 1.0
    return features


def option_tokens(descriptor: FieldDescriptor) -> tuple[str, ...]:
    """Return the descriptor's option words, normalised once.

    Nothing in the feature blocks uses this: spec section 10.2 keeps option text
    out of the two text blocks. It is here so that a later phase which decides to
    widen the feature set does so through ``extract.normalize.normalize_tokens``,
    the one normalisation every other stream went through, rather than by writing
    a second one beside it.
    """
    tokens: list[str] = []
    for raw in (*descriptor.option_labels, *descriptor.option_values):
        tokens.extend(normalize_tokens(raw))
    return tuple(tokens)


def signal_name(feature: str) -> str:
    """Return the ``Prediction.signals`` spelling of a feature name.

    The block prefix is translated into the vocabulary P3 established for
    evidence, where the part before the colon names where the evidence came from
    rather than what it means.
    """
    block, _, detail = feature.partition(":")
    return f"{_SIGNAL_PREFIX.get(block, 'ngram:other')}:{detail}"


# ---------------------------------------------------------------------------
# The fitted space.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureSpace:
    """A fitted vocabulary: the ordered feature names and their column indices.

    Committed as ``vocab.json`` beside the model. A committed vocabulary is what
    makes the model inspectable: a reviewer can read what it keys on, the model
    card can show the top weighted features per label, and a finding's evidence
    can name the actual n-grams that fired. Hashing would make all three
    impossible in exchange for solving a memory problem this corpus does not have
    (spec section 10.2).
    """

    config: FeatureConfig
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        index = {name: column for column, name in enumerate(self.names)}
        object.__setattr__(self, "_index", index)

    @property
    def index(self) -> Mapping[str, int]:
        """Feature name to column index."""
        index: Mapping[str, int] = self.__dict__["_index"]
        return index

    @property
    def width(self) -> int:
        """The number of columns, which is the model's input dimension."""
        return len(self.names)

    def block_counts(self) -> dict[str, int]:
        """How many columns each block contributes, for the model card."""
        counts: dict[str, int] = {}
        for name in self.names:
            block = name.partition(":")[0]
            counts[block] = counts.get(block, 0) + 1
        return counts

    def to_json(self) -> dict[str, Any]:
        """Emit the committed document."""
        return {
            "schema_version": VOCAB_SCHEMA_VERSION,
            "config": self.config.to_json(),
            "width": self.width,
            "block_counts": self.block_counts(),
            "names": list(self.names),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the committed document, validating as it goes."""
        version = payload.get("schema_version")
        if version != VOCAB_SCHEMA_VERSION:
            raise FeatureSpaceError(
                f"vocabulary: this build reads schema version {VOCAB_SCHEMA_VERSION}, "
                f"found {version!r}"
            )
        config_payload = payload.get("config")
        if not isinstance(config_payload, Mapping):
            raise FeatureSpaceError("vocabulary: config must be an object")
        raw_names = payload.get("names")
        if not isinstance(raw_names, list):
            raise FeatureSpaceError("vocabulary: names must be a list")
        names: list[str] = []
        for item in raw_names:
            if not isinstance(item, str):
                raise FeatureSpaceError(f"vocabulary: a name must be a string, found {item!r}")
            names.append(item)
        if len(set(names)) != len(names):
            raise FeatureSpaceError("vocabulary: a feature name appears twice")
        return cls(config=FeatureConfig.from_json(config_payload), names=tuple(names))


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    """A compressed sparse row matrix, in numpy alone.

    Not a ``scipy.sparse`` matrix, although spec section 10.2 names one, and the
    reason is the runtime dependency list. This structure is what an installed
    wheel needs, and it is a two line adapter away from a real CSR matrix for the
    training script, which has scipy because it has scikit-learn. Keeping scipy
    out of ``src/`` means the audit path installs numpy and onnxruntime and
    nothing else, which is the deployment argument of spec section 5.4 applied to
    one more package.
    """

    indptr: np.typing.NDArray[np.int64]
    indices: np.typing.NDArray[np.int64]
    data: np.typing.NDArray[np.float32]
    shape: tuple[int, int]

    @property
    def rows(self) -> int:
        """The number of rows."""
        return self.shape[0]

    def to_dense(self) -> np.typing.NDArray[np.float32]:
        """Return the dense float32 array the ONNX session takes as input.

        Dense because the exported graph is a matrix multiply and onnxruntime's
        sparse support is not a road worth walking for a page with sixty fields
        and a vocabulary this size. The arithmetic is stated so the choice can be
        checked rather than trusted: one row is ``width`` float32 values, and the
        largest page this tool will ever see is a few hundred rows.
        """
        dense = np.zeros(self.shape, dtype=np.float32)
        for row in range(self.shape[0]):
            start, end = int(self.indptr[row]), int(self.indptr[row + 1])
            dense[row, self.indices[start:end]] = self.data[start:end]
        return dense

    def row_items(self, row: int) -> list[tuple[int, float]]:
        """Return one row's column and value pairs, for evidence extraction."""
        start, end = int(self.indptr[row]), int(self.indptr[row + 1])
        return [
            (int(self.indices[position]), float(self.data[position]))
            for position in range(start, end)
        ]


def fit_feature_space(
    descriptors: Sequence[FieldDescriptor], config: FeatureConfig | None = None
) -> FeatureSpace:
    """Fit the vocabulary on ``descriptors``, which must be the train partition.

    Applies the document-frequency floor and the feature ceiling of ``config`` to
    the two text blocks, and keeps every observed name from the three indicator
    blocks, which are bounded by the attribute space rather than by the corpus
    and number in the dozens rather than the thousands.

    Ties at the feature ceiling are broken by name so that two runs over the same
    corpus produce the same vocabulary, which is the property spec section 18
    calls one seed propagated and which a frequency sort alone does not give.
    """
    resolved = config if config is not None else FeatureConfig()
    document_frequency: dict[str, int] = {}
    for descriptor in descriptors:
        for name in descriptor_features(descriptor, resolved):
            document_frequency[name] = document_frequency.get(name, 0) + 1

    kept: list[str] = []
    kept.extend(
        _capped(document_frequency, BLOCK_CHAR, resolved.char_min_df, resolved.char_max_features)
    )
    kept.extend(
        _capped(document_frequency, BLOCK_WORD, resolved.word_min_df, resolved.word_max_features)
    )
    for block in (BLOCK_CATEGORICAL, BLOCK_OPTION, BLOCK_STRUCTURAL):
        kept.extend(sorted(name for name in document_frequency if name.startswith(f"{block}:")))
    return FeatureSpace(config=resolved, names=tuple(kept))


def _capped(
    document_frequency: Mapping[str, int], block: str, min_df: int, max_features: int
) -> list[str]:
    """Return one block's kept feature names, in a stable order."""
    prefix = f"{block}:"
    candidates = [
        name
        for name, count in document_frequency.items()
        if name.startswith(prefix) and count >= min_df
    ]
    candidates.sort(key=lambda name: (-document_frequency[name], name))
    return sorted(candidates[:max_features])


def featurize(descriptors: Sequence[FieldDescriptor], space: FeatureSpace) -> FeatureMatrix:
    """Return the design matrix for ``descriptors`` under a fitted ``space``.

    The one featurisation, called by ``scripts/train.py`` and by
    ``classify/onnx_model.py`` alike. Spec section 10.2 writes the signature as
    ``featurize(descriptors)``; the fitted vocabulary is a second argument here
    because the same section requires a fixed vocabulary fitted on train and
    committed with the model, and a function that reached for a module-level one
    would be a global that two tests could not use differently.

    A feature the space does not carry is dropped, which is what an unseen
    character n-gram in an unseen locale does at inference time and is the honest
    behaviour: the model has no weight for it, so it contributes nothing rather
    than contributing noise.
    """
    index = space.index
    indptr = [0]
    indices: list[int] = []
    data: list[float] = []
    for descriptor in descriptors:
        row: list[tuple[int, float]] = []
        for name, value in descriptor_features(descriptor, space.config).items():
            column = index.get(name)
            if column is not None:
                row.append((column, value))
        row.sort()
        for column, value in row:
            indices.append(column)
            data.append(value)
        indptr.append(len(indices))
    return FeatureMatrix(
        indptr=np.asarray(indptr, dtype=np.int64),
        indices=np.asarray(indices, dtype=np.int64),
        data=np.asarray(data, dtype=np.float32),
        shape=(len(descriptors), space.width),
    )
