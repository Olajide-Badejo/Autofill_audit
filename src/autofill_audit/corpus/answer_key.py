"""Answer-key emission and schema validation (spec section 5.6).

Keys are separate JSON files and never ``data-truth`` attributes in the
generated HTML. Spec section 5.6 gives the decisive reason: a signal-collection
loop that gathers every ``data-*`` attribute is a reasonable thing for an
extractor to do, and if the truth were in the markup that loop would ingest the
label it is being tested on, inflating every downstream metric by an amount
nobody could easily detect. Physical separation makes that class of leak
structurally impossible rather than merely unintended.

**The schema is generated from the taxonomy, then committed.** The label
enumeration in the schema is built from ``taxonomy.Label``, so it cannot drift
from the code, and the generated document is written to
``answer_key.schema.json`` beside this module so that an external consumer can
read the contract without running Python. A test asserts the committed file
still matches what this module generates, which is what keeps the two honest.

**Validation is a small hand-rolled walk, not a dependency.** The subset of JSON
Schema this document uses is narrow and fully known, and adding a validation
library to a tool that installs with ``pipx`` in order to check its own
generated files is a poor trade. The walker below supports exactly the keywords
the schema uses and raises on any it does not recognise, so the schema cannot
quietly grow a keyword that is never enforced.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources
from typing import Any, Final

from autofill_audit.corpus.families import TEMPLATES, Family
from autofill_audit.corpus.generator import GENERATOR_VERSION, GeneratedForm
from autofill_audit.corpus.profiles import LOCALE_IDS
from autofill_audit.corpus.roles import SlotRole
from autofill_audit.corpus.tiers import Delivery, IdentifierStyle, Tier
from autofill_audit.taxonomy import ALL_LABELS

__all__ = [
    "SCHEMA_FILENAME",
    "SCHEMA_VERSION",
    "answer_key_schema",
    "build_answer_key",
    "committed_schema",
    "validate_answer_key",
    "validate_document",
]

SCHEMA_VERSION: Final[int] = 1
SCHEMA_FILENAME: Final[str] = "answer_key.schema.json"

_PACKAGE = "autofill_audit.corpus"
_SUPPORTED_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "minItems",
        "minLength",
        "minimum",
    }
)


def _string(**extra: Any) -> dict[str, Any]:
    return {"type": "string", **extra}


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _object(properties: dict[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def answer_key_schema() -> dict[str, Any]:
    """Build the answer-key JSON schema from the live taxonomy and enums.

    Every enumeration in the returned document is derived, never typed: the
    label list comes from ``taxonomy.Label``, the locales from the profile
    table, the tiers and delivery kinds from their enums, and the template ids
    from the template set. A schema with a hand-copied label list would be a
    second definition of the taxonomy, which ground rule 6 forbids.
    """
    provenance = _object(
        {
            "slot_key": _string(minLength=1),
            "role": {"type": "string", "enum": sorted(role.value for role in SlotRole)},
            "section": _string(minLength=1),
            "tier": {"type": "string", "enum": sorted(tier.value for tier in Tier)},
            "control": {"type": "string", "enum": ["input", "select", "textarea"]},
            "input_type": _nullable_string(),
            "delivery": {
                "type": "string",
                "enum": sorted(delivery.value for delivery in Delivery),
            },
            "selector_strategy": {
                "type": "string",
                "enum": ["form_name", "id", "nth_of_type", "shadow"],
            },
            "identifier_style": {
                "type": "string",
                "enum": sorted(style.value for style in IdentifierStyle),
            },
            "element_id": _nullable_string(),
            "name": _nullable_string(),
            "declared_autocomplete": _nullable_string(),
            "label_text": _nullable_string(),
            "placeholder": _nullable_string(),
            "shadow_host": _nullable_string(),
            "injection_slot": _nullable_string(),
            "transforms": _string_array(),
        },
        required=[
            "slot_key",
            "role",
            "section",
            "tier",
            "control",
            "input_type",
            "delivery",
            "selector_strategy",
            "identifier_style",
            "element_id",
            "name",
            "declared_autocomplete",
            "label_text",
            "placeholder",
            "shadow_host",
            "injection_slot",
            "transforms",
        ],
    )

    entry = _object(
        {
            "selector": _string(minLength=1),
            "label": {"type": "string", "enum": sorted(label.value for label in ALL_LABELS)},
            "expected_modifiers": _string_array(),
            "provenance": provenance,
        },
        required=["selector", "label", "expected_modifiers", "provenance"],
    )

    page_notes = _object(
        {
            "canvas_pseudo_fields": _string_array(),
            "shadow_hosts": _string_array(),
            "injected_selectors": _string_array(),
        },
        required=["canvas_pseudo_fields", "shadow_hosts", "injected_selectors"],
    )

    document = _object(
        {
            "schema_version": {"type": "integer", "const": SCHEMA_VERSION},
            "generator_version": _string(minLength=1),
            "form_id": _string(minLength=1),
            "family": {"type": "string", "enum": sorted(family.value for family in Family)},
            "template_id": {"type": "string", "enum": sorted(TEMPLATES)},
            "locale": {"type": "string", "enum": sorted(LOCALE_IDS)},
            "tier": {"type": "string", "enum": sorted(tier.value for tier in Tier)},
            "variant": {"type": "integer", "minimum": 0},
            "fields": {"type": "array", "items": entry, "minItems": 1},
            "page_notes": page_notes,
        },
        required=[
            "schema_version",
            "generator_version",
            "form_id",
            "family",
            "template_id",
            "locale",
            "tier",
            "variant",
            "fields",
            "page_notes",
        ],
    )
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = "https://github.com/Olajide-Badejo/autofill-audit/answer_key.schema.json"
    document["title"] = "autofill-audit corpus answer key"
    document["description"] = (
        "Ground truth for one generated form: a CSS selector to taxonomy label "
        "mapping with per-field provenance, plus the page-level facts that are "
        "not form controls."
    )
    return document


def committed_schema() -> dict[str, Any]:
    """Read the committed schema document from the package."""
    text = resources.files(_PACKAGE).joinpath(SCHEMA_FILENAME).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def build_answer_key(form: GeneratedForm) -> dict[str, Any]:
    """Build the answer-key document for one generated form."""
    fields: list[dict[str, Any]] = []
    for control in form.fields:
        fields.append(
            {
                "selector": control.selector,
                "label": control.label.value,
                "expected_modifiers": list(control.modifiers),
                "provenance": {
                    "slot_key": control.slot_key,
                    "role": control.role.value,
                    "section": control.section_key,
                    "tier": control.tier.value,
                    "control": control.tag,
                    "input_type": control.input_type,
                    "delivery": control.delivery.value,
                    "selector_strategy": control.selector_strategy,
                    "identifier_style": control.identifier_style.value,
                    "element_id": control.element_id,
                    "name": control.name,
                    "declared_autocomplete": control.declared,
                    "label_text": control.label_text,
                    "placeholder": control.placeholder,
                    "shadow_host": control.shadow_host_id,
                    "injection_slot": control.injection_slot_id,
                    "transforms": list(control.transforms),
                },
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "form_id": form.form_id,
        "family": form.family.value,
        "template_id": form.template_id,
        "locale": form.locale,
        "tier": form.tier.value,
        "variant": form.variant,
        "fields": fields,
        "page_notes": {
            "canvas_pseudo_fields": list(form.canvas_selectors),
            "shadow_hosts": [
                control.shadow_host_id
                for control in form.shadow_fields
                if control.shadow_host_id is not None
            ],
            "injected_selectors": [control.selector for control in form.injected_fields],
        },
    }


_TYPE_NAMES: Final[dict[str, type | tuple[type, ...]]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    python_type = _TYPE_NAMES[expected]
    return isinstance(value, python_type) and not isinstance(value, bool)


def validate_document(value: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Validate ``value`` against the supported JSON Schema subset.

    Returns a list of human-readable problems, empty when the value conforms.

    Raises:
        ValueError: when the schema uses a keyword this walker does not
            implement. Silently ignoring an unknown keyword would mean a
            constraint that looks enforced and is not.
    """
    unknown = set(schema) - _SUPPORTED_KEYWORDS
    if unknown:
        raise ValueError(f"{path}: unsupported schema keywords {sorted(unknown)}")

    problems: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        options = [expected] if isinstance(expected, str) else list(expected)
        if not any(_type_matches(value, option) for option in options):
            return [f"{path}: expected {' or '.join(options)}, found {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: expected the constant {schema['const']!r}, found {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of the permitted values")
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        problems.append(f"{path}: shorter than the minimum length {schema['minLength']}")
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        problems.append(f"{path}: below the minimum {schema['minimum']}")

    if isinstance(value, dict):
        properties: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    problems.append(f"{path}: unexpected property {key!r}")
        for key, sub_schema in properties.items():
            if key in value:
                problems.extend(validate_document(value[key], sub_schema, path=f"{path}.{key}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                problems.extend(validate_document(item, item_schema, path=f"{path}[{index}]"))

    return problems


def validate_answer_key(document: Any) -> list[str]:
    """Validate one answer-key document, schema first and then the invariants.

    The schema cannot express the two properties that matter most, so they are
    checked here: selectors have to be unique within a form, because a duplicate
    would make one control's ground truth unreachable, and a shadow-hosted or
    injected control has to be listed in ``page_notes`` as well as in
    ``fields``, because P2's extractor reaches those two by a different route
    from every other control and needs to be told they are there.
    """
    problems = validate_document(document, answer_key_schema())
    if problems:
        return problems

    fields: list[dict[str, Any]] = document["fields"]
    selectors = [entry["selector"] for entry in fields]
    duplicates = sorted({name for name in selectors if selectors.count(name) > 1})
    if duplicates:
        problems.append(f"duplicate selectors: {', '.join(duplicates)}")

    notes = document["page_notes"]
    declared_injected = set(notes["injected_selectors"])
    actual_injected = {
        entry["selector"]
        for entry in fields
        if entry["provenance"]["delivery"] == Delivery.INJECTED.value
    }
    if declared_injected != actual_injected:
        problems.append(
            "page_notes.injected_selectors disagrees with the injected fields: "
            f"{sorted(declared_injected)} against {sorted(actual_injected)}"
        )

    declared_hosts = set(notes["shadow_hosts"])
    actual_hosts = {
        entry["provenance"]["shadow_host"]
        for entry in fields
        if entry["provenance"]["delivery"] == Delivery.SHADOW.value
    }
    if declared_hosts != actual_hosts:
        problems.append(
            "page_notes.shadow_hosts disagrees with the shadow fields: "
            f"{sorted(declared_hosts)} against {sorted(actual_hosts)}"
        )
    return problems
