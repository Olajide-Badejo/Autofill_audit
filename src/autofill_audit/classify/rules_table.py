"""The rule table: a data file with structure, not a heuristic pile (spec 10.1).

Three tables live here and nothing else does. ``INTRINSIC_RULES`` reads the
attributes a browser reads first. ``VOCABULARY`` is the multilingual word list,
matched as compiled regexes against the normalised token streams. ``OPTION_RULES``
reads the shape of a ``<select>``'s option list. The engine in ``rules.py`` owns
the precedence between them and owns no vocabulary of its own, so adding a
language is an edit to one table rather than a change to any control flow.

Signal precedence (spec section 10.1), applied in this order and never merged
into a single score:

1. ``INTRINSIC``: ``type``, ``inputmode``, and the structural group role.
2. ``LABEL``: the tokens of a real label.
3. ``IDENTIFIER``: ``name``, ``id``, class, data keys, framework attributes.
4. ``PLACEHOLDER``: the tokens of a placeholder pressed into service as a label.
5. ``CONTEXT``: legend, section heading, preceding text, form accessible name.
6. ``OPTIONS``: the shape of an option list.

The first tier that yields a unique match wins, ties fall through to the next
tier, and a tie surviving every tier yields ``UNKNOWN``. "Unique" is decided by
weight: within a tier each candidate label takes the highest weight of any of its
rules that matched, and the tier resolves only when exactly one label holds the
maximum. That is what gives ``weight`` a job rather than leaving it decoration.

**Ties are a feature and several of them are deliberate.** German writes
``Straße und Hausnummer`` for both a whole street address and the first of
several address lines, and French writes ``Adresse`` for both. In those locales
the label genuinely does not distinguish the two, so both labels carry the same
pattern at the same weight, the tier ties, and the engine falls through to the
identifier. Where the identifier does not distinguish them either, the answer is
``UNKNOWN``, and that is the honest answer rather than a coin toss dressed up as
a classification (law 1).

**Weights are an ordinal scale of five values and mean nothing outside a tier.**
They are never summed, never averaged, and never compared across tiers. The
scale is deliberately coarse: a finer one would invite tuning, and a rule table
tuned against the corpus it is evaluated on is a rule table that has learned the
corpus.

**Locale coverage.** Every entry whose wording belongs to one locale carries that
locale tag, and ``vocabulary_by_locale`` counts them, so "which languages does
this cover" is answered by the table rather than by a claim in a document. Tags
outside the six corpus locales are used where a word is worth having anyway; the
Italian ``cap`` and the Irish ``eircode`` are there because spec section 10.1
names the first of them explicitly and because a postal-code vocabulary that
stops at the corpus is a vocabulary that will be wrong on the first real page it
meets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from autofill_audit.classify.base import ConfidenceTier
from autofill_audit.descriptors import GroupRole
from autofill_audit.taxonomy import Label

__all__ = [
    "INTRINSIC_RULES",
    "OPTION_RULES",
    "RULE_TABLE_VERSION",
    "TIER_PRECEDENCE",
    "TIER_TO_CONFIDENCE",
    "VOCABULARY",
    "WEIGHT_BROAD",
    "WEIGHT_DECISIVE",
    "WEIGHT_MODERATE",
    "WEIGHT_STRONG",
    "WEIGHT_WEAK",
    "IntrinsicField",
    "IntrinsicRule",
    "Rule",
    "SignalTier",
    "labels_with_rules",
    "vocabulary_by_locale",
]

RULE_TABLE_VERSION: Final[str] = "1.0.0"
"""Bumped deliberately whenever a rule is added, removed, or reweighted.

``describe()`` reports it and the run log records it, so a metric can always name
the table that produced it. It is a version of the *table*, not of the engine
that reads it: a change to precedence is a change to ``rules.py`` and to the
package version, and a change to a word list is a change here."""


class SignalTier(StrEnum):
    """Which stream a rule is matched against, and therefore its precedence."""

    INTRINSIC = "intrinsic"
    LABEL = "label"
    IDENTIFIER = "identifier"
    PLACEHOLDER = "placeholder"
    CONTEXT = "context"
    OPTIONS = "options"


TIER_PRECEDENCE: Final[tuple[SignalTier, ...]] = (
    SignalTier.INTRINSIC,
    SignalTier.LABEL,
    SignalTier.IDENTIFIER,
    SignalTier.PLACEHOLDER,
    SignalTier.CONTEXT,
    SignalTier.OPTIONS,
)
"""Spec section 10.1's order, verbatim, as the one place it is written down."""

TIER_TO_CONFIDENCE: Final[dict[SignalTier, ConfidenceTier]] = {
    SignalTier.INTRINSIC: ConfidenceTier.HIGH,
    SignalTier.LABEL: ConfidenceTier.HIGH,
    SignalTier.IDENTIFIER: ConfidenceTier.MEDIUM,
    SignalTier.PLACEHOLDER: ConfidenceTier.MEDIUM,
    SignalTier.CONTEXT: ConfidenceTier.LOW,
    SignalTier.OPTIONS: ConfidenceTier.MEDIUM,
}
"""Spec section 10.1 fixes four of these six: an intrinsic or a label match is
``HIGH``, an identifier or a placeholder match is ``MEDIUM``, a context match is
``LOW``.

It does not say where an option-list match sits, because it lists the option
shape as a precedence tier without giving it a confidence. It is placed at
``MEDIUM``, with the identifier and the placeholder, on the reasoning that an
option list is a structural fact about the control itself rather than prose
found near it: a select offering twelve months is evidence of the same kind as a
name attribute reading ``expmonth``, and evidence of a different kind from a
heading three elements up that happened to mention a card. Placing it at ``LOW``
instead would mean a hostile select with intact options, which is the single most
common shape a real component library produces, could never rise above a note."""

WEIGHT_DECISIVE: Final[int] = 120
"""A compound that names one label and must beat its own components. ``expiry
month`` over ``expiry``, ``weiterer adresszusatz`` over ``adresszusatz``."""

WEIGHT_STRONG: Final[int] = 100
"""A word or phrase that names this label and essentially nothing else."""

WEIGHT_MODERATE: Final[int] = 80
"""Strongly associated, but shared with a neighbouring label in some locale."""

WEIGHT_BROAD: Final[int] = 60
"""Names a family rather than a member: ``address``, ``name``, ``password``."""

WEIGHT_WEAK: Final[int] = 40
"""Corroborating only. Never enough on its own to beat anything above."""

_LOCALE_AGNOSTIC: Final[str] = ""
"""The locale tag of a rule whose wording belongs to no single language."""


@dataclass(frozen=True, slots=True)
class Rule:
    """One ``(pattern, label, weight, signal_name)`` row of spec section 10.1.

    ``locale`` is the one addition, and it earns its place: it is what makes spec
    section 10.1's "a comment per locale-specific entry" mechanically checkable
    instead of a comment that rots.

    There is deliberately no tier on a row. Which tier a vocabulary row fires at
    is a property of the stream it matched, not of the row, and the same row fires
    at ``LABEL`` for one control and at ``IDENTIFIER`` for the next. ``evidence``
    therefore takes the firing tier rather than storing one.
    """

    pattern: re.Pattern[str]
    label: Label
    weight: int
    signal_name: str
    locale: str = _LOCALE_AGNOSTIC

    def evidence(self, tier: SignalTier) -> str:
        """The string appended to ``Prediction.signals`` when this rule fires."""
        return f"{tier.value}:{self.signal_name}"


class IntrinsicField(StrEnum):
    """Which descriptor attribute an intrinsic rule reads.

    Four, and no more. An intrinsic signal is one a browser's own heuristics
    read straight off the element, so the list stops where the element's own
    declarations stop: everything textual is vocabulary, and everything
    structural beyond the detected group is out of scope for a rule table.
    """

    INPUT_TYPE = "input_type"
    INPUTMODE = "inputmode"
    TAG = "tag"
    GROUP_ROLE = "group_role"


@dataclass(frozen=True, slots=True)
class IntrinsicRule:
    """One attribute-equals-value row of the intrinsic tier."""

    field: IntrinsicField
    value: str
    label: Label
    weight: int
    signal_name: str

    def evidence(self) -> str:
        """The string appended to ``Prediction.signals`` when this rule fires."""
        return f"{SignalTier.INTRINSIC.value}:{self.signal_name}"


def _rule(
    pattern: str,
    label: Label,
    weight: int,
    signal_name: str,
    *,
    locale: str = _LOCALE_AGNOSTIC,
) -> Rule:
    """Compile one vocabulary row.

    ``re.IGNORECASE`` is deliberately **not** set. Every stream a rule is matched
    against has already been casefolded by ``extract.normalize``, so a
    case-insensitive match here would be a second, slower, subtly different fold
    layered on top of the documented one.
    """
    return Rule(
        pattern=re.compile(pattern),
        label=label,
        weight=weight,
        signal_name=signal_name,
        locale=locale,
    )


def _exact(token: str) -> str:
    """A pattern matching ``token`` as a whole token in a space-joined stream.

    Needed wherever a word is a prefix or a substring of an unrelated word in the
    same language: German ``Land`` inside ``Bundesland``, Japanese ``国`` inside
    ``国番号``, French ``nom`` inside ``nombre``. A word boundary is not enough
    for the Japanese cases, because ``\\b`` sees no boundary between two ideographs.
    """
    return rf"(?:^| ){re.escape(token)}(?:$| )"


# ---------------------------------------------------------------------------
# The intrinsic tier.
#
# What the element declares about itself. A `type="email"` is very strong (spec
# section 10.1) because a page that bothered to write it meant it, and no other
# signal on the control can be more authoritative about what the control accepts.
#
# `type="password"` appears twice on purpose. It is decisive that the field takes
# a password and says nothing at all about which of the two password labels
# applies, so both rules fire at the same weight, the tier ties, and the decision
# falls through to wording that might distinguish them. Breaking that tie by
# guessing would produce a confident instruction to write the wrong token into
# production markup, which is exactly what law 1 exists to prevent.
# ---------------------------------------------------------------------------

INTRINSIC_RULES: Final[tuple[IntrinsicRule, ...]] = (
    IntrinsicRule(IntrinsicField.INPUT_TYPE, "email", Label.EMAIL, WEIGHT_STRONG, "type-email"),
    IntrinsicRule(IntrinsicField.INPUT_TYPE, "url", Label.URL, WEIGHT_STRONG, "type-url"),
    IntrinsicRule(IntrinsicField.INPUT_TYPE, "tel", Label.TEL, WEIGHT_MODERATE, "type-tel"),
    IntrinsicRule(IntrinsicField.INPUT_TYPE, "month", Label.CC_EXP, WEIGHT_MODERATE, "type-month"),
    IntrinsicRule(
        IntrinsicField.INPUT_TYPE,
        "search",
        Label.NOT_AUTOFILLABLE,
        WEIGHT_STRONG,
        "type-search",
    ),
    IntrinsicRule(
        IntrinsicField.INPUT_TYPE,
        "checkbox",
        Label.NOT_AUTOFILLABLE,
        WEIGHT_MODERATE,
        "type-checkbox",
    ),
    IntrinsicRule(
        IntrinsicField.INPUT_TYPE,
        "password",
        Label.NEW_PASSWORD,
        WEIGHT_BROAD,
        "type-password",
    ),
    IntrinsicRule(
        IntrinsicField.INPUT_TYPE,
        "password",
        Label.CURRENT_PASSWORD,
        WEIGHT_BROAD,
        "type-password",
    ),
    IntrinsicRule(
        IntrinsicField.GROUP_ROLE,
        GroupRole.CC_EXP_MONTH.value,
        Label.CC_EXP_SPLIT_MONTH,
        WEIGHT_STRONG,
        "expiry-pair-month",
    ),
    IntrinsicRule(
        IntrinsicField.GROUP_ROLE,
        GroupRole.CC_EXP_YEAR.value,
        Label.CC_EXP_SPLIT_YEAR,
        WEIGHT_STRONG,
        "expiry-pair-year",
    ),
)


# ---------------------------------------------------------------------------
# The vocabulary, grouped by label, in taxonomy order.
#
# Every row whose wording belongs to one language carries that language's tag.
# Rows with no tag are either English, which is the language the identifier
# conventions of the web are written in whatever the page's own language, or are
# genuinely language independent, such as the `mm yy` shape of a composite expiry.
# ---------------------------------------------------------------------------

_IDENTITY: Final[tuple[Rule, ...]] = (
    # name
    _rule(r"\bfull name\b", Label.NAME, WEIGHT_STRONG, "full-name-words"),
    _rule(r"\bfullname\b", Label.NAME, WEIGHT_STRONG, "full-name-words"),
    _rule(r"\bcomplete name\b", Label.NAME, WEIGHT_STRONG, "full-name-words"),
    # de-DE: "Vollständiger Name" is the German heading for one whole-name field.
    _rule(r"\bvollständige[rn]? name\b", Label.NAME, WEIGHT_STRONG, "name-de", locale="de-DE"),
    # fr-FR: "Nom complet".
    _rule(r"\bnom complet\b", Label.NAME, WEIGHT_STRONG, "name-fr", locale="fr-FR"),
    _rule(r"\bnomcomplet\b", Label.NAME, WEIGHT_STRONG, "name-fr", locale="fr-FR"),
    # ja-JP: the polite form of "name", which is what a Japanese form writes.
    _rule(r"お名前", Label.NAME, WEIGHT_STRONG, "name-ja", locale="ja-JP"),
    _rule(r"\bonamae\b", Label.NAME, WEIGHT_STRONG, "name-ja", locale="ja-JP"),
    _rule(r"\bname\b", Label.NAME, WEIGHT_BROAD, "name-word"),
    # given-name
    _rule(r"\bfirst ?name\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-words"),
    _rule(r"\bgiven ?name\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-words"),
    _rule(r"\bforename\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-words"),
    _rule(r"\bfname\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-words"),
    # de-DE: "Vorname". "Zweiter Vorname" is the middle name and outweighs it below.
    _rule(r"\bvorname\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-de", locale="de-DE"),
    # fr-FR: "Prénom", same relationship with "Deuxième prénom".
    _rule(r"\bpr[ée]nom\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-fr", locale="fr-FR"),
    # ja-JP: the given name is written 名, and its kana companion メイ.
    _rule(_exact("名"), Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-ja", locale="ja-JP"),
    _rule(_exact("メイ"), Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-ja", locale="ja-JP"),
    _rule(r"\bmei\b", Label.GIVEN_NAME, WEIGHT_STRONG, "given-name-ja", locale="ja-JP"),
    # additional-name
    _rule(r"\bmiddle ?name\b", Label.ADDITIONAL_NAME, WEIGHT_STRONG, "middle-name-words"),
    _rule(r"\bmiddle initial\b", Label.ADDITIONAL_NAME, WEIGHT_STRONG, "middle-name-words"),
    # de-DE: literally "second given name", so it has to outweigh "Vorname".
    _rule(
        r"\bzweiter vorname\b",
        Label.ADDITIONAL_NAME,
        WEIGHT_DECISIVE,
        "middle-name-de",
        locale="de-DE",
    ),
    # fr-FR: "Deuxième prénom", same relationship with "Prénom".
    _rule(
        r"\bdeuxi[èe]me pr[ée]nom\b",
        Label.ADDITIONAL_NAME,
        WEIGHT_DECISIVE,
        "middle-name-fr",
        locale="fr-FR",
    ),
    # ja-JP: transliterated, because Japanese names have no middle name of their own.
    _rule(r"ミドルネーム", Label.ADDITIONAL_NAME, WEIGHT_STRONG, "middle-name-ja", locale="ja-JP"),
    # family-name
    _rule(r"\blast ?name\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-words"),
    _rule(r"\bfamily ?name\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-words"),
    _rule(r"\bsurname\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-words"),
    _rule(r"\blname\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-words"),
    # de-DE: "Nachname".
    _rule(r"\bnachname\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-de", locale="de-DE"),
    # fr-FR: the bare "Nom" is the family name; "Nom complet" outweighs it above.
    _rule(_exact("nom"), Label.FAMILY_NAME, WEIGHT_BROAD, "family-name-fr", locale="fr-FR"),
    _rule(
        r"\bnom de famille\b",
        Label.FAMILY_NAME,
        WEIGHT_STRONG,
        "family-name-fr",
        locale="fr-FR",
    ),
    # ja-JP: the family name is written 姓, and its kana companion セイ.
    _rule(_exact("姓"), Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-ja", locale="ja-JP"),
    _rule(_exact("セイ"), Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-ja", locale="ja-JP"),
    _rule(r"\bsei\b", Label.FAMILY_NAME, WEIGHT_STRONG, "family-name-ja", locale="ja-JP"),
    # honorific-prefix
    _rule(r"\btitle\b", Label.HONORIFIC_PREFIX, WEIGHT_MODERATE, "honorific-prefix-words"),
    _rule(r"\bsalutation\b", Label.HONORIFIC_PREFIX, WEIGHT_STRONG, "honorific-prefix-words"),
    _rule(r"\bprefix\b", Label.HONORIFIC_PREFIX, WEIGHT_MODERATE, "honorific-prefix-words"),
    # de-DE: "Anrede" is the form of address, not a job title.
    _rule(
        r"\banrede\b",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-prefix-de",
        locale="de-DE",
    ),
    # fr-FR: "Civilité".
    _rule(
        r"\bcivilit[ée]\b",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-prefix-fr",
        locale="fr-FR",
    ),
    # ja-JP: 敬称.
    _rule(r"敬称", Label.HONORIFIC_PREFIX, WEIGHT_STRONG, "honorific-prefix-ja", locale="ja-JP"),
    # honorific-suffix
    _rule(r"\bsuffix\b", Label.HONORIFIC_SUFFIX, WEIGHT_STRONG, "honorific-suffix-words"),
    # de-DE: "Namenszusatz" is the trailing part of a name, unrelated to Adresszusatz.
    _rule(
        r"\bnamenszusatz\b",
        Label.HONORIFIC_SUFFIX,
        WEIGHT_STRONG,
        "honorific-suffix-de",
        locale="de-DE",
    ),
    # fr-FR: "Suffixe".
    _rule(
        r"\bsuffixe\b",
        Label.HONORIFIC_SUFFIX,
        WEIGHT_STRONG,
        "honorific-suffix-fr",
        locale="fr-FR",
    ),
    # ja-JP: 称号.
    _rule(r"称号", Label.HONORIFIC_SUFFIX, WEIGHT_STRONG, "honorific-suffix-ja", locale="ja-JP"),
    # nickname
    _rule(r"\bnickname\b", Label.NICKNAME, WEIGHT_STRONG, "nickname-words"),
    _rule(r"\bdisplay ?name\b", Label.NICKNAME, WEIGHT_STRONG, "nickname-words"),
    _rule(r"\bscreen ?name\b", Label.NICKNAME, WEIGHT_STRONG, "nickname-words"),
    # de-DE: "Anzeigename".
    _rule(r"\banzeigename\b", Label.NICKNAME, WEIGHT_STRONG, "nickname-de", locale="de-DE"),
    # fr-FR: "Nom affiché".
    _rule(r"\bnom affich[ée]\b", Label.NICKNAME, WEIGHT_STRONG, "nickname-fr", locale="fr-FR"),
    # ja-JP: 表示名.
    _rule(r"表示名", Label.NICKNAME, WEIGHT_STRONG, "nickname-ja", locale="ja-JP"),
)

_CONTACT: Final[tuple[Rule, ...]] = (
    # email
    _rule(r"\be ?mail\b", Label.EMAIL, WEIGHT_STRONG, "email-words"),
    _rule(r"\bmail\b", Label.EMAIL, WEIGHT_MODERATE, "email-words"),
    # fr-FR: "Courriel" is the official French term and appears on public sector forms.
    _rule(r"\bcourriel\b", Label.EMAIL, WEIGHT_STRONG, "email-fr", locale="fr-FR"),
    # ja-JP: メール, usually as メールアドレス.
    _rule(r"メール", Label.EMAIL, WEIGHT_STRONG, "email-ja", locale="ja-JP"),
    # The shape of an example address in a placeholder. RFC 2606 reserves
    # example.com, example.net, and example.org for documentation, so a control
    # whose only text is somebody-at-one-of-those is showing the shape of an
    # email address. The at sign does not survive normalisation, which is why
    # the domain is what this matches rather than the address.
    #
    # This is the one rule that stops a German placeholder reading
    # name@example.com from being read as a name field: the bare token "name"
    # is all that is left of it otherwise, and a whole-name rule fires on that.
    _rule(r"\bexample (?:com|net|org)\b", Label.EMAIL, WEIGHT_MODERATE, "example-domain"),
    # tel
    _rule(r"\bphone\b", Label.TEL, WEIGHT_MODERATE, "phone-words"),
    _rule(r"\btelephone\b", Label.TEL, WEIGHT_MODERATE, "phone-words"),
    _rule(r"\bmobile\b", Label.TEL, WEIGHT_BROAD, "phone-words"),
    # de-DE: "Telefonnummer", "Telefon".
    _rule(r"\btelefon", Label.TEL, WEIGHT_MODERATE, "phone-de", locale="de-DE"),
    # fr-FR: "Téléphone".
    _rule(r"\bt[ée]l[ée]phone\b", Label.TEL, WEIGHT_MODERATE, "phone-fr", locale="fr-FR"),
    # ja-JP: 電話, usually as 電話番号.
    _rule(r"電話", Label.TEL, WEIGHT_MODERATE, "phone-ja", locale="ja-JP"),
    _rule(r"\bdenwabango\b", Label.TEL, WEIGHT_MODERATE, "phone-ja", locale="ja-JP"),
    # tel-national
    _rule(r"\bphonenumber\b", Label.TEL_NATIONAL, WEIGHT_STRONG, "national-number-words"),
    _rule(r"\bnational number\b", Label.TEL_NATIONAL, WEIGHT_STRONG, "national-number-words"),
    _rule(r"\bsubscriber number\b", Label.TEL_NATIONAL, WEIGHT_STRONG, "national-number-words"),
    # de-DE: "Rufnummer" is the number without its dialling code.
    _rule(
        r"\brufnummer\b",
        Label.TEL_NATIONAL,
        WEIGHT_STRONG,
        "national-number-de",
        locale="de-DE",
    ),
    # tel-country-code
    _rule(r"\bcountry code\b", Label.TEL_COUNTRY_CODE, WEIGHT_STRONG, "dialling-code-words"),
    _rule(r"\bdiall?ing code\b", Label.TEL_COUNTRY_CODE, WEIGHT_STRONG, "dialling-code-words"),
    _rule(r"\bphonecc\b", Label.TEL_COUNTRY_CODE, WEIGHT_STRONG, "dialling-code-words"),
    _rule(r"\bphone country\b", Label.TEL_COUNTRY_CODE, WEIGHT_STRONG, "dialling-code-words"),
    # de-DE: "Ländervorwahl", "Vorwahl".
    _rule(
        r"\b(?:länder)?vorwahl\b",
        Label.TEL_COUNTRY_CODE,
        WEIGHT_STRONG,
        "dialling-code-de",
        locale="de-DE",
    ),
    # fr-FR: "Indicatif pays".
    _rule(
        r"\bindicatif\b",
        Label.TEL_COUNTRY_CODE,
        WEIGHT_STRONG,
        "dialling-code-fr",
        locale="fr-FR",
    ),
    # ja-JP: 国番号, which is one token and so never matches the bare 国 of country.
    _rule(r"国番号", Label.TEL_COUNTRY_CODE, WEIGHT_STRONG, "dialling-code-ja", locale="ja-JP"),
    # tel-extension
    _rule(r"\bextension\b", Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-words"),
    _rule(_exact("ext"), Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-words"),
    _rule(r"\bphoneext\b", Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-words"),
    # de-DE: "Durchwahl".
    _rule(r"\bdurchwahl\b", Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-de", locale="de-DE"),
    # fr-FR: "Poste", which is why it is matched as a whole token and not a prefix.
    _rule(_exact("poste"), Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-fr", locale="fr-FR"),
    # ja-JP: 内線, usually as 内線番号.
    _rule(r"内線", Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-ja", locale="ja-JP"),
    _rule(r"\bnaisen\b", Label.TEL_EXTENSION, WEIGHT_STRONG, "extension-ja", locale="ja-JP"),
    # url
    _rule(r"\bwebsite\b", Label.URL, WEIGHT_STRONG, "website-words"),
    _rule(r"\bhomepage\b", Label.URL, WEIGHT_STRONG, "website-words"),
    _rule(_exact("url"), Label.URL, WEIGHT_STRONG, "website-words"),
    # The shape of an example web address, which outweighs the example-domain
    # rule above because a scheme or a www is what separates a web address from
    # an email address once the at sign has been normalised away.
    _rule(r"\bhttps?\b", Label.URL, WEIGHT_STRONG, "url-shape"),
    _rule(r"\bwww\b", Label.URL, WEIGHT_STRONG, "url-shape"),
    # de-DE: "Webseite".
    _rule(r"\bwebseite\b", Label.URL, WEIGHT_STRONG, "website-de", locale="de-DE"),
    # fr-FR: "Site web".
    _rule(r"\bsite web\b", Label.URL, WEIGHT_STRONG, "website-fr", locale="fr-FR"),
    # ja-JP: ウェブサイト.
    _rule(r"ウェブサイト", Label.URL, WEIGHT_STRONG, "website-ja", locale="ja-JP"),
)

_ADDRESS: Final[tuple[Rule, ...]] = (
    # street-address
    _rule(r"\bstreet address\b", Label.STREET_ADDRESS, WEIGHT_MODERATE, "street-words"),
    _rule(r"\bstreet\b", Label.STREET_ADDRESS, WEIGHT_MODERATE, "street-words"),
    _rule(r"\baddress\b", Label.STREET_ADDRESS, WEIGHT_BROAD, "address-word"),
    # de-DE: a German address line is "Straße und Hausnummer"; the sharp s
    # casefolds to ss, which is why the pattern is spelled that way.
    _rule(r"\bstrasse\b", Label.STREET_ADDRESS, WEIGHT_MODERATE, "street-de", locale="de-DE"),
    _rule(r"\bhausnummer\b", Label.STREET_ADDRESS, WEIGHT_MODERATE, "street-de", locale="de-DE"),
    # fr-FR: the bare "Adresse", matched as a whole token so it does not fire on
    # "Adresse e-mail" or "Complément d'adresse" alone.
    _rule(_exact("adresse"), Label.STREET_ADDRESS, WEIGHT_BROAD, "street-fr", locale="fr-FR"),
    # ja-JP: 住所. Moderate rather than strong so that その他の住所情報 and
    # 住所(すべて), which contain it, can outweigh it.
    _rule(r"住所", Label.STREET_ADDRESS, WEIGHT_MODERATE, "street-ja", locale="ja-JP"),
    _rule(r"\bjusho\b", Label.STREET_ADDRESS, WEIGHT_STRONG, "street-ja", locale="ja-JP"),
    # address-line1
    _rule(r"\baddress ?line ?1\b", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-words"),
    _rule(r"\baddress ?1\b", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-words"),
    _rule(r"\bline ?1\b", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-words"),
    # Deliberate tie with street-address: "Street address" is what several
    # locales call the first of two address lines as well as a whole address.
    _rule(r"\bstreet address\b", Label.ADDRESS_LINE1, WEIGHT_MODERATE, "street-words"),
    # de-DE: the same deliberate tie. German writes one wording for both.
    _rule(r"\bstrasse\b", Label.ADDRESS_LINE1, WEIGHT_MODERATE, "street-de", locale="de-DE"),
    _rule(r"\bhausnummer\b", Label.ADDRESS_LINE1, WEIGHT_MODERATE, "street-de", locale="de-DE"),
    # fr-FR: the same deliberate tie.
    _rule(_exact("adresse"), Label.ADDRESS_LINE1, WEIGHT_BROAD, "street-fr", locale="fr-FR"),
    # ja-JP: 町名・番地 is the street-and-number line specifically.
    _rule(r"町名", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-ja", locale="ja-JP"),
    _rule(r"番地", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-ja", locale="ja-JP"),
    _rule(r"\bchomeibanchi\b", Label.ADDRESS_LINE1, WEIGHT_STRONG, "line-1-ja", locale="ja-JP"),
    # address-line2
    _rule(r"\baddress ?line ?2\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-words"),
    _rule(r"\baddress ?2\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-words"),
    _rule(r"\bline ?2\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-words"),
    _rule(r"\bapartment\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "secondary-unit-words"),
    _rule(_exact("apt"), Label.ADDRESS_LINE2, WEIGHT_STRONG, "secondary-unit-words"),
    _rule(r"\bflat\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "secondary-unit-words"),
    _rule(r"\bunit\b", Label.ADDRESS_LINE2, WEIGHT_MODERATE, "secondary-unit-words"),
    # en-NG: Nigerian forms name the estate and a landmark on the second line.
    _rule(r"\bestate\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-ng", locale="en-NG"),
    _rule(r"\blandmark\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-ng", locale="en-NG"),
    # de-DE: "Adresszusatz".
    _rule(r"\badresszusatz\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-de", locale="de-DE"),
    # fr-FR: "Complément d'adresse".
    _rule(r"\bcompl[ée]ment\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-fr", locale="fr-FR"),
    # ja-JP: 建物名・部屋番号, the building and room.
    _rule(r"建物", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-ja", locale="ja-JP"),
    _rule(r"部屋", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-ja", locale="ja-JP"),
    _rule(r"\btatemono\b", Label.ADDRESS_LINE2, WEIGHT_STRONG, "line-2-ja", locale="ja-JP"),
    # address-line3
    _rule(r"\baddress ?line ?3\b", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-words"),
    _rule(r"\baddress ?3\b", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-words"),
    _rule(r"\bline ?3\b", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-words"),
    _rule(_exact("suite"), Label.ADDRESS_LINE3, WEIGHT_BROAD, "line-3-words"),
    # en-NG: "Additional directions" is the third line on Nigerian forms.
    _rule(r"\bdirections\b", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-ng", locale="en-NG"),
    # de-DE: "Weiterer Adresszusatz" has to outweigh the plain "Adresszusatz".
    _rule(
        r"\bweiterer adresszusatz\b",
        Label.ADDRESS_LINE3,
        WEIGHT_DECISIVE,
        "line-3-de",
        locale="de-DE",
    ),
    _rule(
        r"\badresszusatz ?2\b",
        Label.ADDRESS_LINE3,
        WEIGHT_DECISIVE,
        "line-3-de",
        locale="de-DE",
    ),
    # fr-FR: "Complément d'adresse (suite)" has to outweigh "Complément d'adresse".
    _rule(
        r"\bcompl[ée]ment\b.{0,24}\bsuite\b",
        Label.ADDRESS_LINE3,
        WEIGHT_DECISIVE,
        "line-3-fr",
        locale="fr-FR",
    ),
    _rule(
        r"\bcompl[ée]ment ?2\b",
        Label.ADDRESS_LINE3,
        WEIGHT_DECISIVE,
        "line-3-fr",
        locale="fr-FR",
    ),
    # ja-JP: その他の住所情報, "other address information".
    _rule(r"その他", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-ja", locale="ja-JP"),
    _rule(r"\bsonota\b", Label.ADDRESS_LINE3, WEIGHT_STRONG, "line-3-ja", locale="ja-JP"),
    # address-level2, the town or city
    _rule(r"\bcity\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-words"),
    _rule(r"\btown\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-words"),
    _rule(r"\bsuburb\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-words"),
    _rule(r"\blocality\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-words"),
    # de-DE: "Ort", a whole token because it is a fragment of many other words.
    _rule(_exact("ort"), Label.ADDRESS_LEVEL2, WEIGHT_MODERATE, "city-de", locale="de-DE"),
    _rule(r"\bstadt\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-de", locale="de-DE"),
    # fr-FR: "Ville".
    _rule(r"\bville\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-fr", locale="fr-FR"),
    # ja-JP: 市区町村, the municipality.
    _rule(r"市区町村", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-ja", locale="ja-JP"),
    _rule(r"\bshikuchoson\b", Label.ADDRESS_LEVEL2, WEIGHT_STRONG, "city-ja", locale="ja-JP"),
    # address-level1, the state, county, or prefecture
    _rule(r"\bstate\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-words"),
    _rule(r"\bprovince\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-words"),
    _rule(r"\bregion\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-words"),
    # en-GB: British forms ask for a county.
    _rule(r"\bcounty\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-gb", locale="en-GB"),
    # de-DE: "Bundesland".
    _rule(
        r"\bbundesland\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_STRONG,
        "admin-area-de",
        locale="de-DE",
    ),
    # fr-FR: "Région".
    _rule(r"\br[ée]gion\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-fr", locale="fr-FR"),
    # ja-JP: 都道府県, the four words for a prefecture taken together.
    _rule(r"都道府県", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-ja", locale="ja-JP"),
    _rule(r"\btodofuken\b", Label.ADDRESS_LEVEL1, WEIGHT_STRONG, "admin-area-ja", locale="ja-JP"),
    # postal-code. Spec section 10.1 names this vocabulary explicitly.
    _rule(r"\bzip\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-words"),
    _rule(r"\bzipcode\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-words"),
    _rule(r"\bpostal\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-words"),
    _rule(r"\bpostalcode\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-words"),
    _rule(r"\bpost ?code\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-words"),
    # de-DE: "PLZ" and the word it abbreviates.
    _rule(r"\bplz\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-de", locale="de-DE"),
    _rule(r"\bpostleitzahl\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-de", locale="de-DE"),
    # fr-FR: "Code postal" and the abbreviation "CP", the latter as a whole token.
    _rule(r"\bcode postal\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-fr", locale="fr-FR"),
    _rule(r"\bcodepostal\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-fr", locale="fr-FR"),
    _rule(_exact("cp"), Label.POSTAL_CODE, WEIGHT_MODERATE, "postcode-fr", locale="fr-FR"),
    # it-IT: "CAP", outside the corpus locales and named by spec section 10.1.
    _rule(_exact("cap"), Label.POSTAL_CODE, WEIGHT_MODERATE, "postcode-it", locale="it-IT"),
    # ja-JP: 郵便番号 and its romanisation.
    _rule(r"郵便番号", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-ja", locale="ja-JP"),
    _rule(r"\byubinbango\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-ja", locale="ja-JP"),
    # ja-JP: the postal mark. Present because spec section 10.1 names it and
    # because it is what a Japanese form prints beside the box. It cannot fire
    # today: the normalisation of spec section 9.7 treats a lone symbol character
    # as a delimiter, so the mark never reaches a token stream. Keeping the row
    # and saying so is better than a silent omission; making it reachable is a
    # deliberate normalisation change with golden-snapshot churn, and it is
    # recorded as such in the notes for P4 rather than smuggled in here.
    _rule(r"〒", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-mark-ja", locale="ja-JP"),
    # ie-IE and in-IN: two more national names for the same field.
    _rule(r"\beircode\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-ie", locale="ie-IE"),
    _rule(r"\bpin ?code\b", Label.POSTAL_CODE, WEIGHT_STRONG, "postcode-in", locale="in-IN"),
    # country
    _rule(r"\bcountry\b", Label.COUNTRY, WEIGHT_BROAD, "country-words"),
    # de-DE: "Land", a whole token so it does not fire inside "Bundesland".
    _rule(_exact("land"), Label.COUNTRY, WEIGHT_BROAD, "country-de", locale="de-DE"),
    # fr-FR: "Pays".
    _rule(r"\bpays\b", Label.COUNTRY, WEIGHT_BROAD, "country-fr", locale="fr-FR"),
    # ja-JP: 国, a whole token so it does not fire inside 国番号 or 国名.
    _rule(_exact("国"), Label.COUNTRY, WEIGHT_BROAD, "country-ja", locale="ja-JP"),
    _rule(r"\bkuni\b", Label.COUNTRY, WEIGHT_BROAD, "country-ja", locale="ja-JP"),
    # country-name
    _rule(r"\bcountry ?name\b", Label.COUNTRY_NAME, WEIGHT_STRONG, "country-name-words"),
    # ja-JP: 国名.
    _rule(r"国名", Label.COUNTRY_NAME, WEIGHT_STRONG, "country-name-ja", locale="ja-JP"),
    _rule(r"\bkunimei\b", Label.COUNTRY_NAME, WEIGHT_STRONG, "country-name-ja", locale="ja-JP"),
    # organization
    _rule(r"\bcompany\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-words"),
    _rule(r"\borgani[sz]ation\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-words"),
    _rule(r"\bemployer\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-words"),
    _rule(r"\bbusiness ?name\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-words"),
    # de-DE: "Firma".
    _rule(r"\bfirma\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-de", locale="de-DE"),
    # fr-FR: "Société", "Entreprise".
    _rule(
        r"\bsoci[ée]t[ée]\b",
        Label.ORGANIZATION,
        WEIGHT_STRONG,
        "organization-fr",
        locale="fr-FR",
    ),
    _rule(
        r"\bentreprise\b",
        Label.ORGANIZATION,
        WEIGHT_STRONG,
        "organization-fr",
        locale="fr-FR",
    ),
    # ja-JP: 会社名.
    _rule(r"会社", Label.ORGANIZATION, WEIGHT_STRONG, "organization-ja", locale="ja-JP"),
    _rule(r"\bkaishamei\b", Label.ORGANIZATION, WEIGHT_STRONG, "organization-ja", locale="ja-JP"),
)

_PAYMENT: Final[tuple[Rule, ...]] = (
    # cc-name
    _rule(r"\bname on card\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-words"),
    _rule(r"\bnameoncard\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-words"),
    _rule(r"\bcard ?holder\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-words"),
    # de-DE: "Karteninhaber".
    _rule(r"\bkarteninhaber\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-de", locale="de-DE"),
    # fr-FR: "Titulaire de la carte".
    _rule(r"\btitulaire\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-fr", locale="fr-FR"),
    # ja-JP: カード名義.
    _rule(r"カード名義", Label.CC_NAME, WEIGHT_STRONG, "cardholder-ja", locale="ja-JP"),
    _rule(r"\bcardmeigi\b", Label.CC_NAME, WEIGHT_STRONG, "cardholder-ja", locale="ja-JP"),
    # cc-number
    _rule(r"\bcard ?number\b", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-words"),
    _rule(r"\bcardnum\b", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-words"),
    _rule(r"\bcc ?number\b", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-words"),
    _rule(_exact("pan"), Label.CC_NUMBER, WEIGHT_MODERATE, "card-number-words"),
    # de-DE: "Kartennummer".
    _rule(
        r"\bkartennummer\b",
        Label.CC_NUMBER,
        WEIGHT_STRONG,
        "card-number-de",
        locale="de-DE",
    ),
    # fr-FR: "Numéro de carte".
    _rule(
        r"\bnum[ée]ro de carte\b",
        Label.CC_NUMBER,
        WEIGHT_STRONG,
        "card-number-fr",
        locale="fr-FR",
    ),
    _rule(r"\bnumerocarte\b", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-fr", locale="fr-FR"),
    # ja-JP: カード番号.
    _rule(r"カード番号", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-ja", locale="ja-JP"),
    _rule(r"\bcardbango\b", Label.CC_NUMBER, WEIGHT_STRONG, "card-number-ja", locale="ja-JP"),
    # cc-exp
    _rule(r"\bexpir(?:y|ation) date\b", Label.CC_EXP, WEIGHT_STRONG, "expiry-words"),
    _rule(r"\bexpiration\b", Label.CC_EXP, WEIGHT_MODERATE, "expiry-words"),
    _rule(r"\bexpiry\b", Label.CC_EXP, WEIGHT_MODERATE, "expiry-words"),
    _rule(r"\bcardexpiry\b", Label.CC_EXP, WEIGHT_STRONG, "expiry-words"),
    _rule(r"\bvalid thru\b", Label.CC_EXP, WEIGHT_STRONG, "expiry-words"),
    # de-DE: "Gültig bis".
    _rule(r"\bg[üu]ltig bis\b", Label.CC_EXP, WEIGHT_STRONG, "expiry-de", locale="de-DE"),
    # fr-FR: "Date d'expiration".
    _rule(r"\bdate d expiration\b", Label.CC_EXP, WEIGHT_STRONG, "expiry-fr", locale="fr-FR"),
    # ja-JP: 有効期限.
    _rule(r"有効期限", Label.CC_EXP, WEIGHT_STRONG, "expiry-ja", locale="ja-JP"),
    # cc-exp-month
    _rule(r"\bexpir(?:y|ation) month\b", Label.CC_EXP_MONTH, WEIGHT_DECISIVE, "expiry-month-words"),
    _rule(r"\bexp ?month\b", Label.CC_EXP_MONTH, WEIGHT_DECISIVE, "expiry-month-words"),
    _rule(r"\bcardexpmonth\b", Label.CC_EXP_MONTH, WEIGHT_DECISIVE, "expiry-month-words"),
    _rule(r"\bmonth\b", Label.CC_EXP_MONTH, WEIGHT_MODERATE, "month-word"),
    # de-DE: "Monat", and the compound "Gültig bis (Monat)".
    _rule(r"\bmonat\b", Label.CC_EXP_MONTH, WEIGHT_MODERATE, "month-de", locale="de-DE"),
    _rule(
        r"\bg[üu]ltig bis monat\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "expiry-month-de",
        locale="de-DE",
    ),
    # fr-FR: "Mois", and "Mois d'expiration".
    _rule(r"\bmois\b", Label.CC_EXP_MONTH, WEIGHT_MODERATE, "month-fr", locale="fr-FR"),
    _rule(
        r"\bmois d expiration\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "expiry-month-fr",
        locale="fr-FR",
    ),
    # ja-JP: 月 as a whole token, and the compound 有効期限(月).
    _rule(_exact("月"), Label.CC_EXP_MONTH, WEIGHT_MODERATE, "month-ja", locale="ja-JP"),
    _rule(
        r"有効期限.{0,4}月",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "expiry-month-ja",
        locale="ja-JP",
    ),
    # cc-exp-year
    _rule(r"\bexpir(?:y|ation) year\b", Label.CC_EXP_YEAR, WEIGHT_DECISIVE, "expiry-year-words"),
    _rule(r"\bexp ?year\b", Label.CC_EXP_YEAR, WEIGHT_DECISIVE, "expiry-year-words"),
    _rule(r"\bcardexpyear\b", Label.CC_EXP_YEAR, WEIGHT_DECISIVE, "expiry-year-words"),
    _rule(r"\byear\b", Label.CC_EXP_YEAR, WEIGHT_MODERATE, "year-word"),
    # de-DE: "Jahr", and the compound "Gültig bis (Jahr)".
    _rule(r"\bjahr\b", Label.CC_EXP_YEAR, WEIGHT_MODERATE, "year-de", locale="de-DE"),
    _rule(
        r"\bg[üu]ltig bis jahr\b",
        Label.CC_EXP_YEAR,
        WEIGHT_DECISIVE,
        "expiry-year-de",
        locale="de-DE",
    ),
    # fr-FR: "Année", and "Année d'expiration".
    _rule(r"\bann[ée]e\b", Label.CC_EXP_YEAR, WEIGHT_MODERATE, "year-fr", locale="fr-FR"),
    _rule(
        r"\bann[ée]e d expiration\b",
        Label.CC_EXP_YEAR,
        WEIGHT_DECISIVE,
        "expiry-year-fr",
        locale="fr-FR",
    ),
    # ja-JP: 年 as a whole token, and the compound 有効期限(年).
    _rule(_exact("年"), Label.CC_EXP_YEAR, WEIGHT_MODERATE, "year-ja", locale="ja-JP"),
    _rule(
        r"有効期限.{0,4}年",
        Label.CC_EXP_YEAR,
        WEIGHT_DECISIVE,
        "expiry-year-ja",
        locale="ja-JP",
    ),
    # cc-csc
    _rule(r"\bsecurity code\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    _rule(r"\bsecuritycode\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    _rule(r"\bcvv2?\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    _rule(_exact("cvc"), Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    _rule(_exact("csc"), Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    _rule(r"\bcard verification\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-words"),
    # de-DE: "Prüfziffer", with its transliteration for identifiers.
    _rule(r"\bpr[üu]fziffer\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-de", locale="de-DE"),
    _rule(r"\bpruefziffer\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-de", locale="de-DE"),
    # fr-FR: "Cryptogramme visuel".
    _rule(r"\bcryptogramme\b", Label.CC_CSC, WEIGHT_STRONG, "security-code-fr", locale="fr-FR"),
    # ja-JP: セキュリティコード, in full. The bare セキュリティ is the Japanese
    # word for "security" and is what a form's own security section is headed
    # with, so a pattern that stopped there matched the heading above a login
    # password field and called it a card verification code.
    _rule(r"セキュリティコード", Label.CC_CSC, WEIGHT_STRONG, "security-code-ja", locale="ja-JP"),
    # cc-type
    _rule(r"\bcard ?type\b", Label.CC_TYPE, WEIGHT_STRONG, "card-type-words"),
    _rule(r"\bcard ?brand\b", Label.CC_TYPE, WEIGHT_STRONG, "card-type-words"),
    # de-DE: "Kartentyp".
    _rule(r"\bkartentyp\b", Label.CC_TYPE, WEIGHT_STRONG, "card-type-de", locale="de-DE"),
    # fr-FR: "Type de carte".
    _rule(r"\btype de carte\b", Label.CC_TYPE, WEIGHT_STRONG, "card-type-fr", locale="fr-FR"),
    # ja-JP: カードの種類.
    _rule(r"カードの種類", Label.CC_TYPE, WEIGHT_STRONG, "card-type-ja", locale="ja-JP"),
    # transaction-amount
    _rule(r"\bamount\b", Label.TRANSACTION_AMOUNT, WEIGHT_STRONG, "amount-words"),
    _rule(r"\bprice\b", Label.TRANSACTION_AMOUNT, WEIGHT_MODERATE, "amount-words"),
    _rule(r"\btotal\b", Label.TRANSACTION_AMOUNT, WEIGHT_MODERATE, "amount-words"),
    # de-DE: "Betrag".
    _rule(r"\bbetrag\b", Label.TRANSACTION_AMOUNT, WEIGHT_STRONG, "amount-de", locale="de-DE"),
    # fr-FR: "Montant".
    _rule(r"\bmontant\b", Label.TRANSACTION_AMOUNT, WEIGHT_STRONG, "amount-fr", locale="fr-FR"),
    # ja-JP: 金額.
    _rule(r"金額", Label.TRANSACTION_AMOUNT, WEIGHT_STRONG, "amount-ja", locale="ja-JP"),
    _rule(r"\bkingaku\b", Label.TRANSACTION_AMOUNT, WEIGHT_STRONG, "amount-ja", locale="ja-JP"),
)

_CREDENTIALS: Final[tuple[Rule, ...]] = (
    # username
    _rule(r"\buser ?name\b", Label.USERNAME, WEIGHT_STRONG, "username-words"),
    _rule(r"\buser ?id\b", Label.USERNAME, WEIGHT_STRONG, "username-words"),
    _rule(r"\bhandle\b", Label.USERNAME, WEIGHT_MODERATE, "username-words"),
    _rule(r"\blogin\b", Label.USERNAME, WEIGHT_MODERATE, "username-words"),
    # de-DE: "Benutzername".
    _rule(r"\bbenutzername\b", Label.USERNAME, WEIGHT_STRONG, "username-de", locale="de-DE"),
    # fr-FR: "Identifiant".
    _rule(r"\bidentifiant\b", Label.USERNAME, WEIGHT_STRONG, "username-fr", locale="fr-FR"),
    # ja-JP: ユーザー名.
    _rule(r"ユーザー", Label.USERNAME, WEIGHT_STRONG, "username-ja", locale="ja-JP"),
    # new-password. The bare word ties with current-password on purpose; see below.
    _rule(r"\bnew ?password\b", Label.NEW_PASSWORD, WEIGHT_DECISIVE, "new-password-words"),
    _rule(r"\bconfirm ?password\b", Label.NEW_PASSWORD, WEIGHT_DECISIVE, "new-password-words"),
    _rule(r"\bpassword ?confirm\b", Label.NEW_PASSWORD, WEIGHT_DECISIVE, "new-password-words"),
    _rule(r"\bcreate ?password\b", Label.NEW_PASSWORD, WEIGHT_DECISIVE, "new-password-words"),
    _rule(r"\brepeat password\b", Label.NEW_PASSWORD, WEIGHT_DECISIVE, "new-password-words"),
    _rule(r"\bpassword\b", Label.NEW_PASSWORD, WEIGHT_BROAD, "password-word"),
    # de-DE: "Passwort bestätigen", "Passwort wiederholen".
    _rule(
        r"\bpasswort (?:best[äa]tigen|wiederholen)\b",
        Label.NEW_PASSWORD,
        WEIGHT_DECISIVE,
        "new-password-de",
        locale="de-DE",
    ),
    _rule(
        r"\bneues passwort\b",
        Label.NEW_PASSWORD,
        WEIGHT_DECISIVE,
        "new-password-de",
        locale="de-DE",
    ),
    _rule(r"\bpasswort\b", Label.NEW_PASSWORD, WEIGHT_BROAD, "password-de", locale="de-DE"),
    # fr-FR: "Confirmer le mot de passe", and the bare "Mot de passe".
    _rule(
        r"\bconfirmer le mot de passe\b",
        Label.NEW_PASSWORD,
        WEIGHT_DECISIVE,
        "new-password-fr",
        locale="fr-FR",
    ),
    _rule(
        r"\bmotdepasse ?2\b",
        Label.NEW_PASSWORD,
        WEIGHT_DECISIVE,
        "new-password-fr",
        locale="fr-FR",
    ),
    _rule(r"\bmot de passe\b", Label.NEW_PASSWORD, WEIGHT_BROAD, "password-fr", locale="fr-FR"),
    _rule(r"\bmotdepasse\b", Label.NEW_PASSWORD, WEIGHT_BROAD, "password-fr", locale="fr-FR"),
    # ja-JP: パスワード(確認), and the bare パスワード.
    _rule(
        r"パスワード.{0,4}確認",
        Label.NEW_PASSWORD,
        WEIGHT_DECISIVE,
        "new-password-ja",
        locale="ja-JP",
    ),
    _rule(r"パスワード", Label.NEW_PASSWORD, WEIGHT_BROAD, "password-ja", locale="ja-JP"),
    # current-password. Every broad row here has a twin above at the same weight.
    #
    # That is the point. A field labelled only "Password" is a login field on a
    # login page and a registration field on a registration page, and the control
    # itself carries nothing that separates the two. The tier ties, the engine
    # falls through, and if nothing else distinguishes them the answer is UNKNOWN.
    # Breaking the tie either way would print a confident instruction to write the
    # wrong token, and a wrong CRITICAL costs more than a missed one.
    _rule(r"\bcurrent ?password\b", Label.CURRENT_PASSWORD, WEIGHT_DECISIVE, "old-password-words"),
    _rule(r"\bold ?password\b", Label.CURRENT_PASSWORD, WEIGHT_DECISIVE, "old-password-words"),
    _rule(r"\bexisting password\b", Label.CURRENT_PASSWORD, WEIGHT_DECISIVE, "old-password-words"),
    _rule(r"\bpassword\b", Label.CURRENT_PASSWORD, WEIGHT_BROAD, "password-word"),
    # de-DE: "Aktuelles Passwort", and the bare "Passwort".
    _rule(
        r"\baktuelles passwort\b",
        Label.CURRENT_PASSWORD,
        WEIGHT_DECISIVE,
        "old-password-de",
        locale="de-DE",
    ),
    _rule(r"\bpasswort\b", Label.CURRENT_PASSWORD, WEIGHT_BROAD, "password-de", locale="de-DE"),
    # fr-FR: the bare "Mot de passe".
    _rule(
        r"\bmot de passe\b",
        Label.CURRENT_PASSWORD,
        WEIGHT_BROAD,
        "password-fr",
        locale="fr-FR",
    ),
    _rule(r"\bmotdepasse\b", Label.CURRENT_PASSWORD, WEIGHT_BROAD, "password-fr", locale="fr-FR"),
    # ja-JP: the bare パスワード.
    _rule(r"パスワード", Label.CURRENT_PASSWORD, WEIGHT_BROAD, "password-ja", locale="ja-JP"),
    # one-time-code
    _rule(r"\bverification ?code\b", Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-words"),
    _rule(r"\bone ?time ?code\b", Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-words"),
    _rule(_exact("otp"), Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-words"),
    _rule(
        r"\bauth(?:entication)? ?code\b", Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-words"
    ),
    _rule(r"\bconfirmation ?code\b", Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-words"),
    # de-DE: "Bestätigungscode".
    _rule(
        r"\bbest[äa]tigungscode\b",
        Label.ONE_TIME_CODE,
        WEIGHT_STRONG,
        "one-time-code-de",
        locale="de-DE",
    ),
    # fr-FR: "Code de vérification".
    _rule(
        r"\bcode de v[ée]rification\b",
        Label.ONE_TIME_CODE,
        WEIGHT_STRONG,
        "one-time-code-fr",
        locale="fr-FR",
    ),
    # ja-JP: 認証コード.
    _rule(r"認証コード", Label.ONE_TIME_CODE, WEIGHT_STRONG, "one-time-code-ja", locale="ja-JP"),
    # bday
    _rule(r"\bdate of birth\b", Label.BDAY, WEIGHT_STRONG, "birth-date-words"),
    _rule(r"\bbirth ?date\b", Label.BDAY, WEIGHT_STRONG, "birth-date-words"),
    _rule(r"\bbirthday\b", Label.BDAY, WEIGHT_STRONG, "birth-date-words"),
    _rule(_exact("dob"), Label.BDAY, WEIGHT_STRONG, "birth-date-words"),
    # de-DE: "Geburtsdatum".
    _rule(r"\bgeburtsdatum\b", Label.BDAY, WEIGHT_STRONG, "birth-date-de", locale="de-DE"),
    # fr-FR: "Date de naissance".
    _rule(r"\bdate de naissance\b", Label.BDAY, WEIGHT_STRONG, "birth-date-fr", locale="fr-FR"),
    _rule(r"\bdatenaissance\b", Label.BDAY, WEIGHT_STRONG, "birth-date-fr", locale="fr-FR"),
    # ja-JP: 生年月日.
    _rule(r"生年月日", Label.BDAY, WEIGHT_STRONG, "birth-date-ja", locale="ja-JP"),
    _rule(r"\bseinengappi\b", Label.BDAY, WEIGHT_STRONG, "birth-date-ja", locale="ja-JP"),
    # sex
    _rule(r"\bgender\b", Label.SEX, WEIGHT_STRONG, "sex-words"),
    _rule(_exact("sex"), Label.SEX, WEIGHT_STRONG, "sex-words"),
    # de-DE: "Geschlecht".
    _rule(r"\bgeschlecht\b", Label.SEX, WEIGHT_STRONG, "sex-de", locale="de-DE"),
    # fr-FR: "Sexe".
    _rule(r"\bsexe\b", Label.SEX, WEIGHT_STRONG, "sex-fr", locale="fr-FR"),
    # ja-JP: 性別.
    _rule(r"性別", Label.SEX, WEIGHT_STRONG, "sex-ja", locale="ja-JP"),
    _rule(r"\bseibetsu\b", Label.SEX, WEIGHT_STRONG, "sex-ja", locale="ja-JP"),
)

_EXTRA: Final[tuple[Rule, ...]] = (
    # COMPOSITE_UNSPLIT: one control collecting what the specification splits.
    _rule(r"\bfull ?address\b", Label.COMPOSITE_UNSPLIT, WEIGHT_STRONG, "whole-address-words"),
    _rule(r"\bcomplete address\b", Label.COMPOSITE_UNSPLIT, WEIGHT_STRONG, "whole-address-words"),
    # de-DE: "Vollständige Anschrift".
    _rule(
        r"\banschrift\b",
        Label.COMPOSITE_UNSPLIT,
        WEIGHT_STRONG,
        "whole-address-de",
        locale="de-DE",
    ),
    # fr-FR: "Adresse complète".
    _rule(
        r"\badresse compl[èe]te\b",
        Label.COMPOSITE_UNSPLIT,
        WEIGHT_STRONG,
        "whole-address-fr",
        locale="fr-FR",
    ),
    # ja-JP: 住所(すべて).
    _rule(
        r"住所.{0,4}すべて",
        Label.COMPOSITE_UNSPLIT,
        WEIGHT_STRONG,
        "whole-address-ja",
        locale="ja-JP",
    ),
    # A control whose text names a street *and* a town or a postal code is
    # collecting a whole address in one box, which is what the composite extra
    # is for. This is the shape a hostile page leaves behind when it strips the
    # label and keeps a sample value in the placeholder, and it has to outweigh
    # the individual address rules that each match one word of it.
    #
    # Two words of different address levels, never two of the same: "City or
    # town" and "Straße und Hausnummer" each name one level twice, and a rule
    # that counted words rather than levels would call both of them composites.
    _rule(
        r"\b(?:street|strasse|rue|adresse)\b.{0,32}"
        r"\b(?:city|town|ville|ort|stadt|zip|postcode|postal|plz)\b",
        Label.COMPOSITE_UNSPLIT,
        WEIGHT_DECISIVE,
        "several-address-parts",
    ),
    # ja-JP: a Japanese address is written outermost first, so the postal code
    # or the prefecture comes before the municipality and the street.
    _rule(
        r"\b(?:郵便番号|都道府県)\b.{0,32}\b(?:市区町村|番地|住所)\b",
        Label.COMPOSITE_UNSPLIT,
        WEIGHT_DECISIVE,
        "several-address-parts-ja",
        locale="ja-JP",
    ),
    # The month-and-year shape of a single expiry input. Locale independent
    # except for the letter the locale uses for "year": Y in English and
    # Japanese, J for Jahr in German, A for année in French.
    _rule(r"\bmm ?yy\b", Label.COMPOSITE_UNSPLIT, WEIGHT_DECISIVE, "mmyy-shape"),
    _rule(r"\bmm ?jj\b", Label.COMPOSITE_UNSPLIT, WEIGHT_DECISIVE, "mmyy-shape", locale="de-DE"),
    _rule(r"\bmm ?aa\b", Label.COMPOSITE_UNSPLIT, WEIGHT_DECISIVE, "mmyy-shape", locale="fr-FR"),
    _rule(r"\bexpdate\b", Label.COMPOSITE_UNSPLIT, WEIGHT_DECISIVE, "mmyy-shape"),
    _rule(r"\bfulladdress\b", Label.COMPOSITE_UNSPLIT, WEIGHT_STRONG, "whole-address-words"),
    # NOT_AUTOFILLABLE: the highest-volume real label (spec section 7.2). A search
    # box, a quantity spinner, a coupon field, a comment area, a consent checkbox.
    _rule(r"\bsearch\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-words"),
    _rule(r"\bsitesearch\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-words"),
    # de-DE: "Suche".
    _rule(r"\bsuche\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-de", locale="de-DE"),
    # fr-FR: "Recherche", "Rechercher".
    _rule(r"\brecherch", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-fr", locale="fr-FR"),
    # ja-JP: 検索.
    _rule(r"検索", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-ja", locale="ja-JP"),
    _rule(r"\bkensaku\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "search-ja", locale="ja-JP"),
    _rule(r"\bquantity\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "quantity-words"),
    _rule(_exact("qty"), Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "quantity-words"),
    # de-DE: "Menge".
    _rule(r"\bmenge\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "quantity-de", locale="de-DE"),
    # fr-FR: "Quantité".
    _rule(
        r"\bquantit[ée]\b",
        Label.NOT_AUTOFILLABLE,
        WEIGHT_STRONG,
        "quantity-fr",
        locale="fr-FR",
    ),
    # ja-JP: 数量.
    _rule(r"数量", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "quantity-ja", locale="ja-JP"),
    _rule(r"\bsuryo\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "quantity-ja", locale="ja-JP"),
    _rule(r"\bpromo", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-words"),
    _rule(r"\bcoupon\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-words"),
    _rule(r"\bvoucher", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-words"),
    _rule(r"\bdiscount code\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-words"),
    # de-DE: "Gutscheincode".
    _rule(r"\bgutschein", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-de", locale="de-DE"),
    # fr-FR: "Code promo", covered by the promo prefix above; "codepromo" as an id.
    _rule(r"\bcodepromo\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-fr", locale="fr-FR"),
    # ja-JP: クーポン.
    _rule(r"クーポン", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "coupon-ja", locale="ja-JP"),
    _rule(r"\bnotes\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-words"),
    _rule(r"\bcomments?\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-words"),
    _rule(r"\binstructions\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-words"),
    _rule(r"\bmessage\b", Label.NOT_AUTOFILLABLE, WEIGHT_MODERATE, "free-text-words"),
    # de-DE: "Anmerkungen".
    _rule(
        r"\banmerkungen\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-de", locale="de-DE"
    ),
    # ja-JP: 備考.
    _rule(r"備考", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-ja", locale="ja-JP"),
    _rule(r"\bbiko\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "free-text-ja", locale="ja-JP"),
    _rule(r"\bterms\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-words"),
    _rule(r"\bconsent\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-words"),
    _rule(r"\bnewsletter\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-words"),
    _rule(r"\bmarketing\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-words"),
    _rule(r"\bopt ?in\b", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-words"),
    # de-DE: "Verkaufsbedingungen", "akzeptiere".
    _rule(
        r"\b(?:verkaufs|geschäfts)bedingungen\b",
        Label.NOT_AUTOFILLABLE,
        WEIGHT_STRONG,
        "consent-de",
        locale="de-DE",
    ),
    # fr-FR: "conditions de vente".
    _rule(
        r"\bconditions de vente\b",
        Label.NOT_AUTOFILLABLE,
        WEIGHT_STRONG,
        "consent-fr",
        locale="fr-FR",
    ),
    # ja-JP: 利用規約.
    _rule(r"利用規約", Label.NOT_AUTOFILLABLE, WEIGHT_STRONG, "consent-ja", locale="ja-JP"),
)

VOCABULARY: Final[tuple[Rule, ...]] = (
    _IDENTITY + _CONTACT + _ADDRESS + _PAYMENT + _CREDENTIALS + _EXTRA
)
"""Every text rule, in taxonomy order. Matched against the label, identifier,
placeholder, and context streams in turn, at whichever tier the engine is on.

The same word list serves all four streams on purpose. What a word means does not
change with where on the element it was written; what changes is how much the
placement is worth, and that is the tier's job, not the vocabulary's."""


# ---------------------------------------------------------------------------
# The option tier.
#
# Matched against the normalised option labels and values of a `<select>`, joined.
# This is the last tier, so it decides only for a control that nothing else could
# name: a hostile component-library select with no label and a generated id, whose
# options are nonetheless intact and completely diagnostic.
# ---------------------------------------------------------------------------

OPTION_RULES: Final[tuple[Rule, ...]] = (
    # A twelve-month list. English, French, Nigerian, and British forms number
    # them; German names them; Japanese suffixes the counter.
    _rule(
        r"\b01\b.{0,120}\b12\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "month-list",
    ),
    _rule(
        r"\bjanuar\b.{0,200}\bdezember\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "month-list-de",
        locale="de-DE",
    ),
    _rule(
        r"\bjanuary\b.{0,200}\bdecember\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "month-list",
    ),
    _rule(
        r"\bjanvier\b.{0,200}\bd[ée]cembre\b",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "month-list-fr",
        locale="fr-FR",
    ),
    _rule(
        r"1月.{0,120}12月",
        Label.CC_EXP_MONTH,
        WEIGHT_DECISIVE,
        "month-list-ja",
        locale="ja-JP",
    ),
    # A run of adjacent four-digit years starting in this century.
    _rule(
        r"\b20\d\d\b .{0,4}\b20\d\d\b",
        Label.CC_EXP_YEAR,
        WEIGHT_DECISIVE,
        "year-run",
    ),
    # Card brands.
    _rule(r"\bvisa\b", Label.CC_TYPE, WEIGHT_STRONG, "card-brand-list"),
    _rule(r"\bmastercard\b", Label.CC_TYPE, WEIGHT_STRONG, "card-brand-list"),
    _rule(
        r"\bamerican express\b",
        Label.CC_TYPE,
        WEIGHT_STRONG,
        "card-brand-list",
    ),
    _rule(_exact("amex"), Label.CC_TYPE, WEIGHT_STRONG, "card-brand-list"),
    _rule(_exact("jcb"), Label.CC_TYPE, WEIGHT_STRONG, "card-brand-list"),
    # en-NG: Verve is the Nigerian domestic card scheme.
    _rule(
        _exact("verve"),
        Label.CC_TYPE,
        WEIGHT_STRONG,
        "card-brand-list-ng",
        locale="en-NG",
    ),
    # fr-FR: Carte Bancaire is the French domestic scheme.
    _rule(
        r"\bcarte bancaire\b",
        Label.CC_TYPE,
        WEIGHT_STRONG,
        "card-brand-list-fr",
        locale="fr-FR",
    ),
    # A sex option list.
    _rule(r"\bfemale\b", Label.SEX, WEIGHT_STRONG, "sex-list"),
    _rule(_exact("male"), Label.SEX, WEIGHT_STRONG, "sex-list"),
    # de-DE: "Weiblich", "Männlich".
    _rule(
        r"\bweiblich\b",
        Label.SEX,
        WEIGHT_STRONG,
        "sex-list-de",
        locale="de-DE",
    ),
    # fr-FR: "Femme", "Homme".
    _rule(
        r"\bfemme\b",
        Label.SEX,
        WEIGHT_STRONG,
        "sex-list-fr",
        locale="fr-FR",
    ),
    # ja-JP: 女性, 男性.
    _rule(
        r"女性",
        Label.SEX,
        WEIGHT_STRONG,
        "sex-list-ja",
        locale="ja-JP",
    ),
    # A list of honorifics.
    _rule(
        r"\bmrs\b.{0,40}\b(?:ms|miss|dr)\b",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-list",
    ),
    # de-DE: "Herr", "Frau".
    _rule(
        r"\bherr\b.{0,40}\bfrau\b",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-list-de",
        locale="de-DE",
    ),
    # fr-FR: "M.", "Mme".
    _rule(
        r"\bmme\b",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-list-fr",
        locale="fr-FR",
    ),
    # ja-JP: 様, さん.
    _rule(
        r"様",
        Label.HONORIFIC_PREFIX,
        WEIGHT_STRONG,
        "honorific-list-ja",
        locale="ja-JP",
    ),
    # A country list, named by the countries every corpus locale offers.
    _rule(
        r"\bunited (?:states|kingdom)\b",
        Label.COUNTRY,
        WEIGHT_MODERATE,
        "country-list",
    ),
    _rule(_exact("nigeria"), Label.COUNTRY, WEIGHT_MODERATE, "country-list"),
    _rule(_exact("japan"), Label.COUNTRY, WEIGHT_MODERATE, "country-list"),
    _rule(_exact("germany"), Label.COUNTRY, WEIGHT_MODERATE, "country-list"),
    # de-DE: "Deutschland", "Österreich".
    _rule(
        r"\bdeutschland\b",
        Label.COUNTRY,
        WEIGHT_MODERATE,
        "country-list-de",
        locale="de-DE",
    ),
    # fr-FR: "Belgique", "Allemagne".
    _rule(
        r"\b(?:belgique|allemagne)\b",
        Label.COUNTRY,
        WEIGHT_MODERATE,
        "country-list-fr",
        locale="fr-FR",
    ),
    # ja-JP: 日本.
    _rule(
        r"日本",
        Label.COUNTRY,
        WEIGHT_MODERATE,
        "country-list-ja",
        locale="ja-JP",
    ),
    # A dialling-code list is a country list with the codes beside the names, and
    # it has to outweigh the country list it contains. Three bare runs of digits
    # is what separates them, and it is the one shape no country list has.
    _rule(
        r"\b\d{1,3}\b.{0,60}\b\d{1,3}\b.{0,60}\b\d{1,3}\b",
        Label.TEL_COUNTRY_CODE,
        WEIGHT_STRONG,
        "dialling-code-list",
    ),
    # An administrative-area list, by the areas each corpus locale offers.
    _rule(
        r"\bcalifornia\b|\bnew york\b|\btexas\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-us",
        locale="en-US",
    ),
    _rule(
        r"\bgreater london\b|\bwest midlands\b|\bmerseyside\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-gb",
        locale="en-GB",
    ),
    _rule(
        r"\blagos\b|\babuja\b|\brivers\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-ng",
        locale="en-NG",
    ),
    _rule(
        r"\bbayern\b|\bhessen\b|\bniedersachsen\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-de",
        locale="de-DE",
    ),
    _rule(
        r"\bbretagne\b|\bnormandie\b|\boccitanie\b",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-fr",
        locale="fr-FR",
    ),
    # ja-JP: prefectures end in 都, 道, 府, or 県.
    _rule(
        r"東京都|大阪府|北海道|.県",
        Label.ADDRESS_LEVEL1,
        WEIGHT_MODERATE,
        "admin-area-list-ja",
        locale="ja-JP",
    ),
)


def labels_with_rules() -> frozenset[Label]:
    """Every label at least one rule in any of the three tables can produce.

    Read by ``scripts/check_reachability.py`` for law 2 clause (c). Reading it
    from the tables rather than from a list means the check cannot drift from
    the code it is checking.
    """
    from_text = {rule.label for rule in VOCABULARY}
    from_options = {rule.label for rule in OPTION_RULES}
    from_intrinsic = {rule.label for rule in INTRINSIC_RULES}
    return frozenset(from_text | from_options | from_intrinsic)


def vocabulary_by_locale() -> dict[str, int]:
    """Count the rules tagged for each locale, plus the locale-agnostic rows.

    The locale-agnostic rows are counted under the empty string. A caller that
    wants a readable table renders that key as whatever it likes; naming it here
    would put a display string in a data module.
    """
    counts: dict[str, int] = {}
    rules: Iterable[Rule] = (*VOCABULARY, *OPTION_RULES)
    for rule in rules:
        counts[rule.locale] = counts.get(rule.locale, 0) + 1
    return counts


_ALLOWED_WEIGHTS: Final[frozenset[int]] = frozenset(
    {WEIGHT_DECISIVE, WEIGHT_STRONG, WEIGHT_MODERATE, WEIGHT_BROAD, WEIGHT_WEAK}
)

assert set(TIER_TO_CONFIDENCE) == set(SignalTier), "every tier needs a confidence"
assert set(TIER_PRECEDENCE) == set(SignalTier), "the precedence order must name every tier"
assert len(TIER_PRECEDENCE) == len(SignalTier), "the precedence order must not repeat a tier"
assert all(rule.weight in _ALLOWED_WEIGHTS for rule in (*VOCABULARY, *OPTION_RULES)), (
    "weights are a five-value ordinal scale; a sixth value would invite tuning"
)
assert all(rule.weight in _ALLOWED_WEIGHTS for rule in INTRINSIC_RULES), (
    "intrinsic rules share the same ordinal scale"
)
