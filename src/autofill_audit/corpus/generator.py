"""Seeded composition of forms across template, locale, tier, and variant.

The algorithm is spec section 8.1, in order, with step 8 as an assertion rather
than a test because a corpus with an incomplete answer key silently becomes a
corpus with wrong metrics.

**Stable hashing.** Python's built-in ``hash()`` is randomised per process for
strings, which is the single most likely cause of a generator that is
deterministic within one run and not across two. The per-form seed is a BLAKE2b
digest of the joined axis strings, truncated to sixty-four bits.

**The axis tuple carries the template id.** Spec section 8.1 writes the axes as
``(family, locale, tier, variant)`` because in that sketch the family is the
atom. Spec section 8.6 then makes the *template* the atom of the split, and the
realised grid carries five templates per family, so two templates of one family
at the same locale, tier, and variant would draw the same seed and therefore the
same sample values. The template id is part of the digest input for that reason,
and the family stays in it so the input is a superset of the specification's
rather than a replacement for it.

**The expiry year window.** A card expiry select has to offer years near the
present or it is not a card expiry select, and spec section 9.5 has the
extractor detect the pair against the *current* year. A hardcoded window would
expire. So the base year is an explicit generator input that defaults to the
current year and is recorded in the manifest: the corpus is a deterministic
function of the seed and the base year together, and passing the manifest's base
year back reproduces the bytes exactly, indefinitely.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from jinja2 import Environment, PackageLoader, StrictUndefined

from autofill_audit.corpus import domcheck
from autofill_audit.corpus.families import (
    TEMPLATES,
    Family,
    ItemKind,
    Section,
    Template,
)
from autofill_audit.corpus.profiles import LOCALE_IDS, LocaleProfile, load_profile
from autofill_audit.corpus.roles import (
    Control,
    OptionKind,
    RoleSpec,
    SlotRole,
    spec_for,
)
from autofill_audit.corpus.selectors import (
    form_name_selector,
    id_selector,
    join_shadow,
    looks_generated,
    nth_of_type_path,
)
from autofill_audit.corpus.tiers import (
    INJECTED_FIELD_DELAY_MS,
    MIXED_TIERS,
    Declaration,
    Delivery,
    IdentifierStyle,
    Tier,
    partial_declaration,
    wrong_declaration_value,
)
from autofill_audit.corpus.values import ValueProvider
from autofill_audit.taxonomy import Label

__all__ = [
    "GENERATOR_VERSION",
    "Cell",
    "GeneratedField",
    "GeneratedForm",
    "GridSpec",
    "RenderSection",
    "Row",
    "build_form",
    "default_base_year",
    "grid_from",
    "iter_forms",
    "render",
    "stable_hash",
]

GENERATOR_VERSION: Final[str] = "1.0.0"
"""Bumped deliberately whenever the emitted bytes change for an unchanged seed.
Recorded in every answer key and in the corpus manifest, so that a corpus can
always say which generator produced it."""

_EXPIRY_YEAR_SPAN: Final[int] = 11
_CANVAS_FAMILIES: Final[frozenset[Family]] = frozenset({Family.CHECKOUT})
"""Spec section 8.4 asks for one canvas-rendered pseudo-field per hostile
checkout form, and nowhere else."""

_SUMMARY_FAMILIES: Final[frozenset[Family]] = frozenset({Family.CHECKOUT, Family.ADDRESS})

_HOSTILE_STYLE_CYCLE: Final[tuple[IdentifierStyle, ...]] = (
    IdentifierStyle.BARE,
    IdentifierStyle.LEGACY_NAME,
    IdentifierStyle.HEX_ID,
    IdentifierStyle.NUMBERED,
    IdentifierStyle.UNDERSCORED,
)
"""The first five hostile controls of a form take one style each, in this order,
so that every branch of the selector preference order of spec section 9.3 is
exercised by the corpus itself and not only by unit tests. Later controls draw
at random from the same set."""

_CLEAN_REQUIRED_RATE: Final[float] = 0.6
_PARTIAL_REQUIRED_RATE: Final[float] = 0.4
_PARTIAL_EXAMPLE_PLACEHOLDER_RATE: Final[float] = 0.5


def default_base_year() -> int:
    """Return the year the expiry selects are built around by default."""
    return dt.date.today().year


def stable_hash(seed: int, *parts: str) -> int:
    """Return a process-stable 64-bit seed for one form.

    Parts are joined with a unit separator so that no two different axis tuples
    can concatenate to the same string.
    """
    payload = "\x1f".join((str(seed), *parts))
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


@dataclass(slots=True)
class GeneratedField:
    """One control, fully decided, before and after selector assignment.

    Mutable on purpose, unlike ``FieldDescriptor``. Descriptors are frozen
    because three classifiers share them; this object never leaves the
    generator, and the selector pass has to walk the finished document tree
    before it can know a positional path, which a frozen object would turn into
    a rebuild of the whole structure.
    """

    slot_key: str
    role: SlotRole
    label: Label
    section_key: str
    modifiers: tuple[str, ...]
    tier: Tier
    tag: str
    delivery: Delivery = Delivery.STATIC
    identifier_style: IdentifierStyle = IdentifierStyle.SEMANTIC
    element_id: str | None = None
    name: str | None = None
    label_text: str | None = None
    label_after: bool = False
    placeholder: str | None = None
    declared: str | None = None
    input_type: str | None = None
    inputmode: str | None = None
    maxlength: int | None = None
    required: bool = False
    options: tuple[tuple[str, str], ...] = ()
    shadow_host_id: str | None = None
    injection_slot_id: str | None = None
    transforms: tuple[str, ...] = ()
    selector: str = ""
    selector_strategy: str = ""
    control_index: int = 1


@dataclass(slots=True)
class Cell:
    """One ``div.field``: usually one control, occasionally an ungrouped pair."""

    fields: list[GeneratedField] = field(default_factory=list)
    cell_id: str | None = None
    canvas_id: str | None = None
    canvas_note: str = ""


@dataclass(slots=True)
class Row:
    """One row of cells, a ``div`` or, for a grouped pair, a ``fieldset``."""

    cells: list[Cell] = field(default_factory=list)
    tag: str = "div"
    legend: str | None = None
    type_index: int = 1


@dataclass(slots=True)
class RenderSection:
    """One section of the form."""

    key: str
    heading: str
    rows: list[Row] = field(default_factory=list)
    tag: str = "section"
    element_id: str | None = None
    tier: Tier = Tier.CLEAN
    type_index: int = 1


@dataclass(slots=True)
class GeneratedForm:
    """One generated form: its markup structure and its ground truth."""

    form_id: str
    family: Family
    template_id: str
    locale: str
    tier: Tier
    variant: int
    lang: str
    title: str
    form_name: str
    submit_text: str
    sections: list[RenderSection] = field(default_factory=list)
    fields: list[GeneratedField] = field(default_factory=list)
    injected_fields: list[GeneratedField] = field(default_factory=list)
    shadow_fields: list[GeneratedField] = field(default_factory=list)
    canvas_selectors: list[str] = field(default_factory=list)
    summary: dict[str, str] | None = None
    summary_heading: str = ""
    summary_ship_to: str = ""
    summary_contact_at: str = ""
    injection_delay_ms: int = INJECTED_FIELD_DELAY_MS


@dataclass(frozen=True, slots=True)
class GridSpec:
    """The axes of one generation run."""

    seed: int
    families: tuple[Family, ...]
    locales: tuple[str, ...]
    tiers: tuple[Tier, ...]
    variants: int
    base_year: int

    def template_ids(self) -> tuple[str, ...]:
        """Return the templates in scope, in declaration order."""
        return tuple(
            template_id
            for template_id, template in TEMPLATES.items()
            if template.family in self.families
        )

    def cells(self) -> Iterator[tuple[str, str, Tier, int]]:
        """Yield every ``(template_id, locale, tier, variant)`` in the grid.

        The order is fixed and nested template, locale, tier, variant, so that
        two runs write their files in the same order and a directory diff
        compares like with like.
        """
        for template_id in self.template_ids():
            for locale in self.locales:
                for tier in self.tiers:
                    for variant in range(self.variants):
                        yield template_id, locale, tier, variant


@dataclass(slots=True)
class _Counters:
    """Per-form identifier bookkeeping."""

    control: int = 0
    hostile: int = 0
    shadow_host: int = 0
    used_ids: set[str] = field(default_factory=set)
    used_names: set[str] = field(default_factory=set)

    def unique_id(self, candidate: str) -> str:
        """Return ``candidate``, suffixed if the document already uses it."""
        return self._unique(candidate, self.used_ids)

    def unique_name(self, candidate: str) -> str:
        """Return ``candidate``, suffixed if the document already uses it."""
        return self._unique(candidate, self.used_names)

    @staticmethod
    def _unique(candidate: str, taken: set[str]) -> str:
        chosen = candidate
        suffix = 2
        while chosen in taken:
            chosen = f"{candidate}{suffix}"
            suffix += 1
        taken.add(chosen)
        return chosen


def _section_tiers(section_count: int, tier: Tier, rng: np.random.Generator) -> list[Tier]:
    """Return the tier of each section.

    For every tier but ``mixed`` this is uniform. For ``mixed`` the draw is
    forced to contain at least one clean and at least one hostile section: a
    mixed form whose sections all landed on one tier would be an ordinary form
    of that tier under the wrong name, and it would quietly thin whichever slice
    it was drawn away from.
    """
    if tier is not Tier.MIXED:
        return [tier] * section_count
    drawn = [MIXED_TIERS[int(rng.integers(0, len(MIXED_TIERS)))] for _ in range(section_count)]
    if Tier.HOSTILE not in drawn:
        drawn[int(rng.integers(0, section_count))] = Tier.HOSTILE
    if Tier.CLEAN not in drawn:
        candidates = [index for index, value in enumerate(drawn) if value is not Tier.HOSTILE]
        if candidates:
            drawn[candidates[int(rng.integers(0, len(candidates)))]] = Tier.CLEAN
    return drawn


def _expand_section(
    section: Section, profile: LocaleProfile, rng: np.random.Generator
) -> list[SlotRole]:
    """Expand a section's items into the concrete slots this locale carries."""
    roles: list[SlotRole] = []
    for item in section.items:
        if item.kind is ItemKind.FIELD:
            assert item.role is not None
            roles.append(item.role)
            continue
        table = profile.name_blocks if item.kind is ItemKind.NAME_BLOCK else profile.address_blocks
        for role in table[item.style]:
            presence = profile.presence_of(role)
            if presence >= 1.0 or float(rng.random()) < presence:
                roles.append(role)
    return roles


_RowPlan = tuple[str, str | None, list[list[SlotRole]]]


def _plan_rows(roles: Sequence[SlotRole], profile: LocaleProfile, hostile: bool) -> list[_RowPlan]:
    """Group a section's slots into rows of cells.

    Two groupings matter here, and both are structural facts rather than styling.

    The split-expiry pair: outside the hostile tier it is wrapped in a fieldset
    with a legend, which is the grouping spec section 9.5 has the extractor
    detect. Inside the hostile tier the two selects share one container with no
    fieldset and no legend, which is the ungrouped split field of spec 8.4.

    The locale's own row groups: German puts the postal code beside the town,
    American forms put city, state, and ZIP on one line. The hostile tier drops
    these, because a hostile page has no considered layout to drop.
    """
    rows: list[_RowPlan] = []
    index = 0
    while index < len(roles):
        role = roles[index]
        pair_follows = (
            role is SlotRole.CARD_EXPIRY_SPLIT_MONTH
            and index + 1 < len(roles)
            and roles[index + 1] is SlotRole.CARD_EXPIRY_SPLIT_YEAR
        )
        if pair_follows:
            pair = [SlotRole.CARD_EXPIRY_SPLIT_MONTH, SlotRole.CARD_EXPIRY_SPLIT_YEAR]
            if hostile:
                rows.append(("div", None, [pair]))
            else:
                rows.append(
                    (
                        "fieldset",
                        profile.label_for(SlotRole.CARD_EXPIRY),
                        [[pair[0]], [pair[1]]],
                    )
                )
            index += 2
            continue
        if not hostile:
            matched: tuple[SlotRole, ...] | None = None
            for group in profile.row_groups:
                if tuple(roles[index : index + len(group)]) == group:
                    matched = group
                    break
            if matched is not None:
                rows.append(("div", None, [[member] for member in matched]))
                index += len(matched)
                continue
        rows.append(("div", None, [[role]]))
        index += 1
    return rows


def _options_for(
    spec: RoleSpec, profile: LocaleProfile, base_year: int
) -> tuple[tuple[str, str], ...]:
    """Build a select's option list.

    Month and year lists carry no blank first option, deliberately. Spec section
    9.5 detects a split expiry pair by finding twelve month-shaped options beside
    a run of consecutive years, and a blank option would break both counts on
    every form in the corpus, which would make the corpus assert a bug rather
    than the behaviour.
    """
    match spec.option_kind:
        case OptionKind.NONE:
            return ()
        case OptionKind.MONTHS:
            names = profile.options["months"]
            return tuple((f"{number:02d}", names[number - 1]) for number in range(1, 13))
        case OptionKind.YEARS:
            return tuple(
                (str(year), str(year)) for year in range(base_year, base_year + _EXPIRY_YEAR_SPAN)
            )
        case OptionKind.COUNTRIES:
            return (("", ""), *profile.option_pairs["countries"])
        case OptionKind.PHONE_COUNTRY_CODES:
            return (("", ""), *profile.option_pairs["phone_country_codes"])
        case OptionKind.CARD_TYPES:
            return (
                ("", ""),
                *(
                    (value.casefold().replace(" ", ""), value)
                    for value in profile.options["card_types"]
                ),
            )
        case OptionKind.TITLES:
            return (("", ""), *((value, value) for value in profile.options["titles"]))
        case OptionKind.SEX_OPTIONS:
            return (("", ""), *((value, value) for value in profile.options["sex_options"]))
        case OptionKind.ADMIN_AREAS:
            return (("", ""), *((value, value) for value in profile.options["admin_areas"]))
    raise AssertionError(f"unhandled option kind {spec.option_kind!r}")


def _hostile_identity(
    style: IdentifierStyle, counters: _Counters, rng: np.random.Generator
) -> tuple[str | None, str | None]:
    """Return the ``(id, name)`` pair for one hostile-tier control."""
    number = counters.control
    match style:
        case IdentifierStyle.NUMBERED:
            return counters.unique_id(f"input{number}"), None
        case IdentifierStyle.UNDERSCORED:
            shared = f"field_{number}"
            return counters.unique_id(shared), counters.unique_name(shared)
        case IdentifierStyle.LEGACY_NAME:
            return None, counters.unique_name(f"ctl00$txt{number}")
        case IdentifierStyle.HEX_ID:
            suffix = "".join("0123456789abcdef"[int(rng.integers(0, 16))] for _ in range(8))
            return (
                counters.unique_id(f"ctl00_txt{number}_{suffix}"),
                counters.unique_name(f"ctl00$txt{number}"),
            )
        case IdentifierStyle.BARE:
            return None, None
        case IdentifierStyle.SEMANTIC:
            raise AssertionError("semantic identifiers are not a hostile style")
    raise AssertionError(f"unhandled identifier style {style!r}")


def _declaration_value(spec: RoleSpec, modifiers: tuple[str, ...]) -> str | None:
    """Return the correct raw autocomplete value for a control, or None."""
    if not spec.autocomplete_expected:
        return None
    token = spec.declaration
    if token is None:
        return None
    return " ".join((*modifiers, token.value))


def _build_field(
    *,
    role: SlotRole,
    section: Section,
    field_tier: Tier,
    profile: LocaleProfile,
    rng: np.random.Generator,
    values: ValueProvider,
    counters: _Counters,
    base_year: int,
) -> GeneratedField:
    """Decide every attribute of one control, given the tier it belongs to."""
    spec = spec_for(role)
    counters.control += 1
    section_key = section.key
    hostile = field_tier is Tier.HOSTILE
    transforms: list[str] = []

    if hostile:
        position = counters.hostile
        counters.hostile += 1
        style = (
            _HOSTILE_STYLE_CYCLE[position]
            if position < len(_HOSTILE_STYLE_CYCLE)
            else _HOSTILE_STYLE_CYCLE[int(rng.integers(0, len(_HOSTILE_STYLE_CYCLE)))]
        )
        element_id, name = _hostile_identity(style, counters, rng)
        transforms.extend(("label_removed", "generic_identifier"))
    else:
        position = -1
        style = IdentifierStyle.SEMANTIC
        stem = profile.identifier_for(role, spec.identifier)
        element_id = counters.unique_id(f"{section_key}-{stem}")
        name = counters.unique_name(f"{section_key}_{stem}")

    label_text = None if hostile else profile.label_for(role)

    placeholder: str | None
    if hostile:
        if position % 2 == 0:
            placeholder = profile.placeholder_for(role) or profile.label_for(role)
            transforms.append("placeholder_as_label")
        else:
            placeholder = None
            transforms.append("no_text_signal")
    else:
        placeholder = profile.placeholder_for(role)
        if (
            placeholder is None
            and field_tier is Tier.PARTIAL
            and bool(rng.random() < _PARTIAL_EXAMPLE_PLACEHOLDER_RATE)
        ):
            placeholder = values.value_for(spec.value_kind)

    correct = _declaration_value(spec, section.modifiers)
    declared: str | None = None
    if field_tier is Tier.CLEAN:
        declared = correct
    elif field_tier is Tier.PARTIAL and correct is not None:
        outcome = partial_declaration(rng)
        if outcome is Declaration.CORRECT:
            declared = correct
        elif outcome is Declaration.WRONG:
            declared = wrong_declaration_value(rng, spec.declaration)
            transforms.append("wrong_declaration")
        else:
            transforms.append("declaration_absent")

    input_type = spec.input_type
    inputmode = spec.inputmode
    maxlength = spec.maxlength
    if hostile:
        inputmode = None
        maxlength = None
        if input_type is not None and input_type not in {"password", "checkbox"}:
            input_type = "text"
            transforms.append("input_type_degraded")

    required = False
    if field_tier is Tier.CLEAN:
        required = bool(rng.random() < _CLEAN_REQUIRED_RATE)
    elif field_tier is Tier.PARTIAL:
        required = bool(rng.random() < _PARTIAL_REQUIRED_RATE)

    tag = {
        Control.INPUT: "input",
        Control.SELECT: "select",
        Control.TEXTAREA: "textarea",
    }[spec.control]

    return GeneratedField(
        slot_key=f"{section_key}.{role.value}.{counters.control}",
        role=role,
        label=spec.label,
        section_key=section_key,
        modifiers=section.modifiers,
        tier=field_tier,
        tag=tag,
        identifier_style=style,
        element_id=element_id,
        name=name,
        label_text=label_text,
        label_after=input_type == "checkbox",
        placeholder=placeholder,
        declared=declared,
        input_type=input_type,
        inputmode=inputmode,
        maxlength=maxlength,
        required=required,
        options=_options_for(spec, profile, base_year),
        transforms=tuple(transforms),
    )


def _undeterminable_field(section_key: str, counters: _Counters) -> GeneratedField:
    """Build the one control per hostile form a human could not label either.

    Law 2 allows ``UNKNOWN`` in the taxonomy only if something emits it, and the
    honest thing to emit it for is a control that genuinely carries no
    information: a bare text input with a generic id, no label, no placeholder,
    no name, and no declaration. Predicting ``UNKNOWN`` here is the correct
    answer rather than a failure, which is the point spec section 7.2 makes.
    """
    counters.control += 1
    spec = spec_for(SlotRole.UNDETERMINABLE)
    return GeneratedField(
        slot_key=f"{section_key}.{SlotRole.UNDETERMINABLE.value}.{counters.control}",
        role=SlotRole.UNDETERMINABLE,
        label=spec.label,
        section_key=section_key,
        modifiers=(),
        tier=Tier.HOSTILE,
        tag="input",
        identifier_style=IdentifierStyle.NUMBERED,
        element_id=counters.unique_id(f"input{counters.control}"),
        input_type="text",
        transforms=("label_removed", "generic_identifier", "no_text_signal", "undeterminable"),
    )


def _injected_field(
    section_key: str, counters: _Counters, profile: LocaleProfile, role: SlotRole
) -> GeneratedField:
    """Build the one control per hostile form that does not exist at load."""
    counters.control += 1
    spec = spec_for(role)
    return GeneratedField(
        slot_key=f"{section_key}.{role.value}.{counters.control}",
        role=role,
        label=spec.label,
        section_key=section_key,
        modifiers=(),
        tier=Tier.HOSTILE,
        tag="input",
        delivery=Delivery.INJECTED,
        identifier_style=IdentifierStyle.NUMBERED,
        element_id=counters.unique_id(f"input{counters.control}"),
        name=counters.unique_name(f"field_{counters.control}"),
        placeholder=profile.placeholder_for(role) or profile.label_for(role),
        input_type="text",
        injection_slot_id=f"inj-slot-{counters.control}",
        transforms=("label_removed", "generic_identifier", "injected_after_load"),
    )


def _apply_hostile_features(
    form: GeneratedForm,
    profile: LocaleProfile,
    counters: _Counters,
    rng: np.random.Generator,
) -> None:
    """Add the per-form hostile features of spec section 8.4.

    All four are per form rather than per field: exactly one shadow-root custom
    element, exactly one control injected after load, exactly one genuinely
    undeterminable control, and, on a checkout, exactly one canvas pseudo-field.
    Making them per field would flood the hostile slice with one failure mode
    and drown the others.
    """
    del rng
    hostile_sections = [section for section in form.sections if section.tier is Tier.HOSTILE]
    if not hostile_sections:
        return
    last = hostile_sections[-1]

    candidates = [
        control
        for control in form.fields
        if control.tier is Tier.HOSTILE
        and control.tag == "input"
        and control.identifier_style is not IdentifierStyle.BARE
        and control.input_type != "checkbox"
    ]
    if candidates:
        chosen = candidates[len(candidates) // 2]
        counters.shadow_host += 1
        chosen.delivery = Delivery.SHADOW
        chosen.shadow_host_id = counters.unique_id(f"ce-{counters.shadow_host}")
        chosen.element_id = None
        if chosen.name is None:
            chosen.name = counters.unique_name(f"field_{counters.control}")
        chosen.transforms = (*chosen.transforms, "shadow_root")
        form.shadow_fields.append(chosen)

    undeterminable = _undeterminable_field(last.key, counters)
    last.rows.append(Row(cells=[Cell(fields=[undeterminable])]))
    form.fields.append(undeterminable)

    if form.family in _CANVAS_FAMILIES:
        canvas_id = counters.unique_id(f"canvas-{last.key}")
        last.rows.append(
            Row(
                cells=[
                    Cell(canvas_id=canvas_id, canvas_note=profile.label_for(SlotRole.CARD_NUMBER))
                ]
            )
        )
        form.canvas_selectors.append(id_selector(canvas_id))

    injected_role = SlotRole.COUPON if form.family is Family.CHECKOUT else SlotRole.SEARCH
    injected = _injected_field(last.key, counters, profile, injected_role)
    last.rows.append(Row(cells=[Cell(cell_id=injected.injection_slot_id)]))
    form.fields.append(injected)
    form.injected_fields.append(injected)


def _assign_one(
    control: GeneratedField,
    *,
    form_name: str,
    anchor: str,
    steps: tuple[tuple[str, int], ...],
) -> None:
    """Apply the preference order of spec section 9.3 to one control."""
    if control.delivery is Delivery.SHADOW:
        assert control.shadow_host_id is not None
        control.selector = join_shadow(id_selector(control.shadow_host_id), "input:nth-of-type(1)")
        control.selector_strategy = "shadow"
        return
    if control.element_id is not None and not looks_generated(control.element_id):
        control.selector = id_selector(control.element_id)
        control.selector_strategy = "id"
        return
    if control.name is not None:
        control.selector = form_name_selector(form_name, control.name)
        control.selector_strategy = "form_name"
        return
    control.selector = nth_of_type_path(anchor, (*steps, (control.tag, control.control_index)))
    control.selector_strategy = "nth_of_type"


def _assign_selectors(form: GeneratedForm) -> None:
    """Walk the finished structure and give every control its selector.

    Runs last, because a positional path is a fact about the document tree and
    the tree is not final until the hostile features have been added.
    """
    section_counts: dict[str, int] = {}
    for section in form.sections:
        section_counts[section.tag] = section_counts.get(section.tag, 0) + 1
        section.type_index = section_counts[section.tag]
        row_counts: dict[str, int] = {}
        for row in section.rows:
            row_counts[row.tag] = row_counts.get(row.tag, 0) + 1
            row.type_index = row_counts[row.tag]

    form_anchor = f'form[name="{form.form_name}"]'
    for section in form.sections:
        stable = section.element_id is not None and not looks_generated(section.element_id)
        if stable:
            assert section.element_id is not None
            anchor = id_selector(section.element_id)
            prefix: tuple[tuple[str, int], ...] = ()
        else:
            anchor = form_anchor
            prefix = ((section.tag, section.type_index),)

        for row in section.rows:
            if row.tag == "fieldset":
                row_steps: tuple[tuple[str, int], ...] = (
                    (row.tag, row.type_index),
                    ("div", 1),
                )
            else:
                row_steps = (("div", row.type_index),)
            for cell_index, cell in enumerate(row.cells, start=1):
                tag_counts: dict[str, int] = {}
                for control in cell.fields:
                    if control.delivery is Delivery.SHADOW:
                        continue
                    tag_counts[control.tag] = tag_counts.get(control.tag, 0) + 1
                    control.control_index = tag_counts[control.tag]
                for control in cell.fields:
                    _assign_one(
                        control,
                        form_name=form.form_name,
                        anchor=anchor,
                        steps=(*prefix, *row_steps, ("div", cell_index)),
                    )

    for control in form.injected_fields:
        assert control.element_id is not None
        control.selector = id_selector(control.element_id)
        control.selector_strategy = "id"

    selectors = [control.selector for control in form.fields]
    assert all(selectors), f"{form.form_id}: every control needs a selector"
    assert len(set(selectors)) == len(selectors), (
        f"{form.form_id}: selectors must be unique within a form"
    )


def build_form(
    template: Template,
    locale: str,
    tier: Tier,
    variant: int,
    *,
    seed: int,
    base_year: int,
) -> GeneratedForm:
    """Compose one form, following the steps of spec section 8.1 in order."""
    form_seed = stable_hash(
        seed, template.family.value, template.template_id, locale, tier.value, str(variant)
    )
    rng = np.random.default_rng(form_seed)
    profile = load_profile(locale)
    values = ValueProvider(profile, form_seed)
    counters = _Counters()

    obscured = tier in {Tier.HOSTILE, Tier.MIXED}
    form = GeneratedForm(
        form_id=f"{template.template_id}-{locale}-{tier.value}-v{variant}",
        family=template.family,
        template_id=template.template_id,
        locale=locale,
        tier=tier,
        variant=variant,
        lang=profile.html_lang,
        title=profile.page_title(template.family.value),
        form_name="f1" if obscured else template.family.value,
        submit_text=profile.page_title(template.family.value),
    )

    tiers = _section_tiers(len(template.sections), tier, rng)
    for section, section_tier in zip(template.sections, tiers, strict=True):
        hostile = section_tier is Tier.HOSTILE
        heading = profile.section_heading(section.key)
        rendered = RenderSection(
            key=section.key,
            # A hostile section keeps a heading element but not an informative
            # heading. Removing the element entirely would change the shape of
            # every positional selector between tiers for no gain; what the
            # hostile tier removes is the information, not the markup.
            heading=heading if not hostile else f"{section.key[:1].upper()}",
            tag="div" if hostile else "section",
            element_id=None if hostile else f"sec-{section.key}",
            tier=section_tier,
        )
        roles = _expand_section(section, profile, rng)
        for row_tag, legend, cells in _plan_rows(roles, profile, hostile):
            row = Row(tag=row_tag, legend=legend)
            for cell_roles in cells:
                cell = Cell()
                for role in cell_roles:
                    control = _build_field(
                        role=role,
                        section=section,
                        field_tier=section_tier,
                        profile=profile,
                        rng=rng,
                        values=values,
                        counters=counters,
                        base_year=base_year,
                    )
                    cell.fields.append(control)
                    form.fields.append(control)
                row.cells.append(cell)
            rendered.rows.append(row)
        form.sections.append(rendered)

    _apply_hostile_features(form, profile, counters, rng)
    _assign_selectors(form)

    if template.family in _SUMMARY_FAMILIES:
        form.summary = values.summary()
        form.summary_heading = profile.summary["heading"]
        form.summary_ship_to = profile.summary["ship_to"]
        form.summary_contact_at = profile.summary["contact_at"]

    return form


_ENVIRONMENT: Final[Environment] = Environment(
    loader=PackageLoader("autofill_audit.corpus", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render(form: GeneratedForm) -> str:
    """Render one form to HTML and assert the answer key covers it exactly.

    This is step 8 of spec section 8.1, and it is an assertion rather than a
    test on purpose: an incomplete answer key does not fail loudly later, it
    silently reports wrong metrics, and the only safe moment to catch it is
    while the form is still in memory.
    """
    html = _ENVIRONMENT.get_template("page.html.j2").render(form=form)
    tree = domcheck.parse(html)

    rendered_controls = domcheck.count_controls(tree)
    expected = sum(1 for control in form.fields if control.delivery is Delivery.STATIC)
    assert rendered_controls == expected, (
        f"{form.form_id}: rendered {rendered_controls} static controls but the answer key "
        f"holds {expected}"
    )
    hosts = len(domcheck.resolve(tree, "af-field"))
    assert hosts == len(form.shadow_fields), (
        f"{form.form_id}: rendered {hosts} shadow hosts against {len(form.shadow_fields)} "
        "in the answer key"
    )
    for control in form.fields:
        if control.delivery is not Delivery.STATIC:
            continue
        found = domcheck.resolve(tree, control.selector)
        assert len(found) == 1, (
            f"{form.form_id}: selector {control.selector!r} resolved to {len(found)} "
            "elements, expected exactly one"
        )
    for control in form.shadow_fields:
        assert control.shadow_host_id is not None
        hosted = domcheck.resolve(tree, id_selector(control.shadow_host_id))
        assert len(hosted) == 1, f"{form.form_id}: shadow host {control.shadow_host_id} missing"
    for control in form.injected_fields:
        assert control.injection_slot_id is not None
        slot = domcheck.resolve(tree, f"#{control.injection_slot_id}")
        assert len(slot) == 1, f"{form.form_id}: injection slot {control.injection_slot_id} missing"
    return html


def grid_from(
    seed: int,
    families: Sequence[str] | None = None,
    locales: Sequence[str] | None = None,
    tiers: Sequence[str] | None = None,
    variants: int = 1,
    base_year: int | None = None,
) -> GridSpec:
    """Build a grid specification from the CLI's string arguments."""
    chosen_families = tuple(Family(value) for value in families) if families else tuple(Family)
    chosen_tiers = tuple(Tier(value) for value in tiers) if tiers else tuple(Tier)
    chosen_locales = tuple(locales) if locales else LOCALE_IDS
    for locale in chosen_locales:
        if locale not in LOCALE_IDS:
            raise ValueError(
                f"unknown locale {locale!r}; known locales are {', '.join(LOCALE_IDS)}"
            )
    if variants < 1:
        raise ValueError("variants must be at least one")
    return GridSpec(
        seed=seed,
        families=chosen_families,
        locales=chosen_locales,
        tiers=chosen_tiers,
        variants=variants,
        base_year=base_year if base_year is not None else default_base_year(),
    )


def iter_forms(grid: GridSpec) -> Iterator[tuple[GeneratedForm, str]]:
    """Yield every form of a grid, with its rendered HTML, in a fixed order."""
    for template_id, locale, tier, variant in grid.cells():
        form = build_form(
            TEMPLATES[template_id],
            locale,
            tier,
            variant,
            seed=grid.seed,
            base_year=grid.base_year,
        )
        yield form, render(form)
