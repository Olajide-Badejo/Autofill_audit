"""The system prompt and the response JSON schema, both versioned.

Spec section 12.2. Prompts are fed pruned field descriptors, never raw HTML,
which is what keeps the input small and the comparison fair.

Why the input is a pruned descriptor and not the page
-----------------------------------------------------

Spec section 12.2 gives three reasons and says the first is sufficient on its
own. **Fairness:** the n-gram model sees descriptors, so a comparison in which
the language model sees the whole document is not a comparison of classifiers,
it is a comparison of input budgets. **Context control:** a real checkout page is
enormous and mostly irrelevant. **Safety:** raw HTML from a user's page may carry
content the user did not intend to send anywhere.

What is dropped, and the one drop that is load bearing
------------------------------------------------------

Spec section 12.2 names three drops and this module makes exactly those three:
geometry (``bbox``), framework attributes, and **the declared ``autocomplete``
value**. The third is the one that decides whether the benchmark measures
anything: leaving the declaration in lets the model read the answer off the page
on every ``clean``-tier form, and the resulting number would measure copying.
``assert_no_declaration_leaks`` exists so that the property is checked rather
than remembered, and a test calls it over the whole corpus.

What is kept, and the rule that settles the cases the specification does not list
--------------------------------------------------------------------------------

Spec section 12.2's keep list is "selector, tag, input type, inputmode, name, id,
class tokens, data keys, all text signals, option labels (truncated), group role,
position". It does not mention ``pattern``, ``maxlength``, ``required``,
``readonly``, or the frame and shadow flags, and ``classify/features.py`` feeds
every one of them to the n-gram model.

So the keep list is read as a floor rather than a ceiling, and the deciding rule
is the fairness argument that the specification gives for the pruning in the
first place: **the language model sees what the n-gram model's featuriser sees,
and nothing more.** Withholding a signal one engine has from the other would tilt
the comparison exactly as far as handing over the whole document would, in the
opposite direction and with a better conscience. The three named drops stand
because none of them reaches the featuriser either.

Raw text signals rather than normalised tokens
----------------------------------------------

The featuriser consumes ``descriptor.norm.text_blob``, which is the section 9.7
normalisation: NFKC, casefold, camelCase and script-boundary splitting. This
module sends the unnormalised ``TextSignals`` instead. That is not extra
information; it is the same information before a lossy preprocessing step that
exists to make a bag of character n-grams tractable. A tokeniser trained on text
reads ``Postleitzahl`` better than it reads ``postleitzahl`` split into pieces,
and spec section 12.2's phrase is "all text signals", which names the
``TextSignals`` member rather than its normalised derivative.

Truncation, and why it is a constant rather than a judgement call
-----------------------------------------------------------------

Spec section 15 requires that a 10 000-character label and a ``<select>`` with
5 000 options both produce a diagnostic rather than a wrong answer. Here they
must additionally not produce a request that exceeds the server's context window,
which would fail the whole page rather than the one field. Every free-text value
is cut at ``TEXT_MAX_CHARS`` and every option list at ``OPTION_LABEL_LIMIT``
entries of ``OPTION_LABEL_MAX_CHARS`` each, with the true option count sent
alongside so that "this select has 5 000 options" survives the truncation as a
fact even though the options themselves do not.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Final

from autofill_audit.descriptors import DeclaredAutocomplete, FieldDescriptor, GroupRole
from autofill_audit.taxonomy import ALL_LABELS, Label

__all__ = [
    "OPTION_LABEL_LIMIT",
    "OPTION_LABEL_MAX_CHARS",
    "PROMPT_VERSION",
    "SCHEMA_NAME",
    "SYSTEM_PROMPT_TEMPLATE",
    "TEXT_MAX_CHARS",
    "assert_no_declaration_leaks",
    "label_enum",
    "parse_retry_message",
    "prompt_fingerprint",
    "prune",
    "prune_all",
    "response_schema",
    "semantic_retry_message",
    "system_prompt",
    "user_message",
]

PROMPT_VERSION: Final[str] = "1.0.0"
"""Written into ``prompt_version`` on every run-log row (spec section 13.1).

A prompt change is the language model's equivalent of a model sha: it changes
what the engine is, and a result file that could not say which prompt produced it
would not be citable. The version is a hand-set string rather than a hash so that
it reads as a version, and ``prompt_fingerprint`` is the mechanical half:
``tests/llm/test_prompts.py`` pins the fingerprint to a committed literal, so
editing the prompt without bumping this constant fails a test rather than
silently making two runs incomparable under one version."""

SCHEMA_NAME: Final[str] = "autofill_field_labels"
"""The name the structured-output request gives the schema. Servers echo it back
in error messages, so it is worth it being the name of this project's schema
rather than a generic one."""

TEXT_MAX_CHARS: Final[int] = 200
"""How much of any one free-text signal is sent.

Two hundred characters is far more than a label, a placeholder, or a legend ever
needs and far less than the ten thousand character label spec section 15
requires the tool to survive. A label longer than this is not carrying field
semantics in the tail."""

OPTION_LABEL_LIMIT: Final[int] = 12
"""How many option labels are sent for a ``<select>``.

Twelve rather than ten because twelve is the length of a month list, and a month
list truncated at ten would lose exactly the shape that identifies it. The full
count travels beside the truncated list, so a five thousand option select is
still recognisable as one."""

OPTION_LABEL_MAX_CHARS: Final[int] = 40
"""How much of any one option label is sent. Country names are the longest
option labels this corpus produces and they fit."""

SYSTEM_PROMPT_TEMPLATE: Final[str] = """\
You classify HTML form fields by their autofill semantics. You will receive a \
JSON array of field descriptors extracted from one page. For each field, return \
exactly one label from the provided list. Use `NOT_AUTOFILLABLE` for controls \
that are not personal-data fields, such as search boxes, quantity inputs, coupon \
codes, free-text comments, and consent checkboxes. Use `UNKNOWN` when the \
evidence is insufficient; do not guess. Return only JSON matching the given \
schema, one entry per input field, with no field omitted and none added.

The `selector` you return for each field must be copied exactly from the \
`selector` of the descriptor it answers, character for character.

The permitted labels are:
{labels}

`confidence` is your own estimate, between 0 and 1, of how likely your label is \
to be correct. It is recorded as a self-reported number and is never treated as \
a calibrated probability."""
"""The system prompt of spec section 12.2, with the label list injected.

The first paragraph is the specification's own wording. The three that follow it
are operational rather than editorial: the selector is the join key between the
response and the request and a paraphrased one cannot be matched, the label list
has to reach the model in prose as well as in the schema's ``enum`` because a
constrained decoder that has never seen the vocabulary spends its first tokens
discovering it, and the confidence sentence tells the model what the number is
for so that the number it produces is at least about the right question.

The list is injected from ``taxonomy.py`` at request time and never written out
here. Ground rule 6: a label string literal in this file would be a second
definition of the taxonomy, and ``scripts/check_reachability.py`` fails the build
on one."""

_PARSE_RETRY_TEMPLATE: Final[str] = (
    "Your previous reply could not be parsed as JSON. The parser reported: "
    "{error}\n\nReturn only the JSON document matching the schema. No prose "
    "before it, no prose after it, no code fence."
)

_SEMANTIC_RETRY_HEADER: Final[str] = (
    "Your previous reply parsed as JSON but did not answer the question asked. "
    "Return exactly one entry for each of the selectors listed below, with the "
    "selector copied character for character, and no entry for any other "
    "selector."
)


def label_enum() -> list[str]:
    """The taxonomy as the schema's ``enum``, sorted for stability.

    Sorted rather than in declaration order so that two runs of the same build
    produce byte-identical requests, which is what makes ``prompt_fingerprint``
    a fingerprint of the prompt rather than of the iteration order of a set.
    """
    return sorted(label.value for label in ALL_LABELS)


def system_prompt() -> str:
    """The system prompt with the label list injected from the taxonomy."""
    return SYSTEM_PROMPT_TEMPLATE.format(labels="\n".join(f"- {name}" for name in label_enum()))


def response_schema() -> dict[str, Any]:
    """The response schema of spec section 12.2, with the label ``enum`` injected.

    Passed with the request so that validity is the server's job rather than the
    parser's. The parser still checks (spec section 12.3 validates before it
    trusts), because a server that quietly ignores the schema is a case this code
    has to survive rather than assume away.
    """
    return {
        "type": "object",
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["selector", "label", "confidence"],
                    "properties": {
                        "selector": {"type": "string"},
                        "label": {"type": "string", "enum": label_enum()},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string", "maxLength": 120},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }


def prompt_fingerprint() -> str:
    """A sha256 over the assembled system prompt and schema.

    The mechanical half of ``PROMPT_VERSION``. It covers the injected label list
    too, so adding a label under the growth rule of spec section 7.3 changes the
    fingerprint, which is correct: it changes what the model may answer.
    """
    payload = json.dumps(
        {"system": system_prompt(), "schema": response_schema()},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pruning (spec section 12.2).
# ---------------------------------------------------------------------------


def _clip(value: str | None, limit: int = TEXT_MAX_CHARS) -> str | None:
    """Return ``value`` cut to ``limit`` characters, or None when it is empty.

    An empty string becomes None so that ``_compact`` drops the key entirely.
    A key whose value is the empty string costs tokens and says nothing that the
    key's absence does not say.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit]


def _compact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None, an empty string, or an empty sequence.

    Not cosmetic. A page of thirty controls, each carrying eleven text signals of
    which two are populated, spends most of its context on the word ``null`` if
    the absent ones are sent. What a descriptor does not have is expressed by the
    key being absent, which is what a reader of JSON expects anyway.
    """
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value is not False
    }


def _text_signals(descriptor: FieldDescriptor) -> dict[str, Any]:
    """Every text signal of spec section 9.4, clipped, with the absent ones gone."""
    text = descriptor.text
    if text.label_for:
        source: str | None = "for"
    elif text.label_ancestor:
        source = "ancestor"
    else:
        source = None
    return _compact(
        {
            "label": _clip(text.label_for or text.label_ancestor),
            "label_source": source,
            "aria_label": _clip(text.aria_label),
            "aria_labelledby": _clip(text.aria_labelledby_text),
            "aria_describedby": _clip(text.aria_describedby_text),
            "title": _clip(text.title),
            "placeholder": _clip(text.placeholder),
            "preceding_text": _clip(text.preceding_text),
            "legend": _clip(text.legend),
            "section_heading": _clip(text.section_heading),
            "form_name": _clip(text.form_accessible_name),
        }
    )


def _options(descriptor: FieldDescriptor) -> dict[str, Any]:
    """The truncated option labels, plus the count that the truncation hides."""
    labels = descriptor.option_labels
    values = descriptor.option_values
    if not labels and not values:
        return {}
    shown = [
        clipped
        for raw in labels[:OPTION_LABEL_LIMIT]
        if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
    ]
    shown_values = [
        clipped
        for raw in values[:OPTION_LABEL_LIMIT]
        if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
    ]
    return _compact(
        {
            "option_labels": shown,
            "option_values": shown_values,
            "option_count": max(len(labels), len(values)),
        }
    )


def prune(descriptor: FieldDescriptor) -> dict[str, Any]:
    """Return the descriptor as spec section 12.2's pruned form.

    Drops geometry, framework attributes, and the declared ``autocomplete``
    value. Keeps everything ``classify/features.py`` feeds the n-gram model, for
    the reason the module docstring gives.
    """
    payload: dict[str, Any] = {
        "selector": descriptor.selector,
        "tag": descriptor.tag,
        "type": descriptor.input_type,
        "inputmode": descriptor.inputmode,
        "pattern": _clip(descriptor.pattern),
        "maxlength": descriptor.maxlength,
        "required": descriptor.required,
        "readonly": descriptor.readonly,
        "disabled": descriptor.disabled,
        "name": _clip(descriptor.name),
        "id": _clip(descriptor.element_id),
        "classes": [
            clipped
            for raw in descriptor.css_classes
            if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
        ],
        "data_keys": [
            clipped
            for raw in descriptor.data_keys
            if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
        ],
        "group_role": (
            None if descriptor.group_role is GroupRole.NONE else descriptor.group_role.value
        ),
        "group_id": descriptor.group_id,
        "position": descriptor.document_index,
        "form_index": descriptor.form_index,
        "fieldset_index": descriptor.fieldset_index,
        "sibling_controls": descriptor.sibling_control_count,
        "in_shadow_root": bool(descriptor.shadow_path),
        "in_frame": bool(descriptor.frame_path),
        "hidden": not descriptor.is_visible,
        "undetectable_reason": descriptor.undetectable_reason,
    }
    payload.update(_options(descriptor))
    text = _text_signals(descriptor)
    if text:
        payload["text"] = text
    return _compact(payload)


def prune_all(fields: Sequence[FieldDescriptor]) -> list[dict[str, Any]]:
    """Prune a whole page, in the order the descriptors were given."""
    return [prune(descriptor) for descriptor in fields]


def assert_no_declaration_leaks(
    pruned: Sequence[Mapping[str, Any]], fields: Sequence[FieldDescriptor]
) -> None:
    """Raise if the declared ``autocomplete`` value influenced the pruned payload.

    The one drop spec section 12.2 calls required, checked rather than trusted.
    A leak here would not crash anything and would not look wrong in a diff; it
    would simply make every ``clean``-tier number in the headline table a measure
    of copying, and it would do it silently.

    The property checked is **independence**, not absence of a substring. Pruning
    the descriptor and pruning the same descriptor with its declaration stripped
    must produce identical payloads. A substring search would be the obvious
    implementation and it would be wrong in both directions: a field named
    ``email`` that also declares ``autocomplete="email"`` would trip it, and a
    declaration that reached the payload through some derived value would not.
    Independence is the actual requirement and it has neither failure.

    Raises:
        ValueError: the declaration changed what the model would be sent.
    """
    for payload, descriptor in zip(pruned, fields, strict=True):
        if not descriptor.declared.raw and not descriptor.declared.token:
            continue
        stripped = prune(replace(descriptor, declared=DeclaredAutocomplete()))
        if dict(payload) != stripped:
            raise ValueError(
                f"{descriptor.selector}: the declared autocomplete value "
                f"{descriptor.declared.raw!r} changed the pruned payload. Spec section "
                "12.2 requires the declaration to be dropped, because leaving it in lets "
                "the model read the answer off the page on every clean-tier form."
            )


# ---------------------------------------------------------------------------
# Messages (spec sections 12.2 and 12.3).
# ---------------------------------------------------------------------------


def user_message(pruned: Sequence[Mapping[str, Any]]) -> str:
    """The request body: the pruned descriptor array, and nothing else."""
    return json.dumps(list(pruned), ensure_ascii=False, indent=None)


def parse_retry_message(error: str) -> str:
    """The one parse retry of spec section 12.3 point 1, with the error text."""
    return _PARSE_RETRY_TEMPLATE.format(error=error)


def semantic_retry_message(missing: Sequence[str], extra: Sequence[str]) -> str:
    """The one semantic retry of spec section 12.3 point 3.

    The specific missing or extra selectors are named, because "your answer was
    wrong" is not a correction and a model given it will produce the same answer.
    """
    lines = [_SEMANTIC_RETRY_HEADER, ""]
    if missing:
        lines.append(f"You omitted {len(missing)} selector(s):")
        lines.extend(f"  {selector}" for selector in missing)
        lines.append("")
    if extra:
        lines.append(f"You invented {len(extra)} selector(s) that were not asked about:")
        lines.extend(f"  {selector}" for selector in extra)
        lines.append("")
    lines.append("Return only the JSON document matching the schema.")
    return "\n".join(lines)


assert Label.UNKNOWN.value in label_enum(), (
    "UNKNOWN must be answerable, or the prompt's instruction not to guess has no "
    "answer the schema permits"
)
assert Label.NOT_AUTOFILLABLE.value in label_enum(), (
    "NOT_AUTOFILLABLE must be answerable, or a search box has no correct label"
)
