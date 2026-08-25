# Findings

This document has two halves.

The **selector contract** below is written at P2 and is stable from now on. It
is the notation every finding, every report renderer, and every answer key uses
to name a form control, and spec section 9.3 requires it to be stated exactly
once and used identically by all three renderers. This is that once.

The **finding catalogue** is written at P3, together with the audit engine that
raises the findings and the fix templates that resolve them. Until then this
document deliberately lists no finding codes, because a catalogue of codes
nothing can emit goes stale before it is finished.

---

## The selector contract

Every field descriptor carries a selector. It has two jobs, and both of them
constrain what it may look like:

1. A human can paste it into DevTools and land on the control the report is
   talking about.
2. An answer key can name a field by it, which makes selector generation part of
   the corpus contract rather than an implementation detail. A change to how
   selectors are built invalidates every committed answer key.

The rules live in `src/autofill_audit/corpus/selectors.py`, which owns the
primitives, and `src/autofill_audit/extract/selector.py`, which applies them to
a document. There is one implementation, imported by both the generator and the
extractor, because two implementations of one schema drift and the drift would
be invisible until an evaluation run silently scored the wrong fields.

### Preference order

A control is named by the first of these that applies.

| Rank | Form | When it applies |
|---|---|---|
| 1 | `#id` | The control has an id, the id is unique within its own root, and the id does not look generated. |
| 2 | `form[name="f"] [name="c"]` | The control has a name, its form has a name, and no other control in that form shares the name. |
| 3 | `anchor > tag:nth-of-type(n) > ...` | Otherwise. The anchor is the nearest ancestor that rank 1 or rank 2 could address on its own, or `html` when there is none. |

Four details in that table are load bearing.

**"Does not look generated" is deliberately narrow.** An id looks generated when
it contains a run of four or more digits, or a run of eight or more hexadecimal
characters. That is the whole test. `input1`, `field_7`, `shipping-postcode`,
and `ctl00_txt3` are all usable; `ctl00_txt3_0a9f4c21`, `mat-input-1234`, and
`ember14235` are not. Note that `ctl00_txt3` is kept while `ctl00_txt3_0a9f4c21`
is rejected: the hex suffix is the discriminator, not the framework prefix. A
wider test would push every hostile-tier control onto a positional path and stop
exercising the id branch at all.

**Rank 2 uses a descendant combinator, not a child combinator.** Spec section
9.3 sketches it as `form[name] > [name="..."]`. A literal child combinator only
matches a control that is an immediate child of the `<form>` element, and real
pages wrap their controls in layout containers, so the child form would produce
selectors that resolve to nothing. This deviation was committed at P1 and the
extractor reproduces it exactly.

**Rank 2 also requires the name to be unique within the form.** That condition
is not in the specification sketch and has to be there: every member of a radio
group shares one name, so without it a group of four radios would get one
selector four times and a report could not name any of them. A shared name falls
through to rank 3.

**`:nth-of-type` counts among siblings of the same tag.** This matters on mixed
markup, where clean sections render as `<section>` and hostile sections render
as `<div>` inside the same form: the two are indexed independently, and an
implementation that counted all siblings would disagree with every answer key on
those forms.

### Boundary separators

Two boundaries cannot be crossed by CSS, so the notation names them explicitly.
Both separators carry a single space either side.

| Boundary | Separator | Example |
|---|---|---|
| Open shadow root | ` >>> ` | `#ce-1 >>> input:nth-of-type(1)` |
| Frame | ` >> `, after a `frame[...]` token | `frame[#pay-frame] >> #card-number` |

A shadow selector is the host's own selector, built by the same preference
order, then the separator, then the selector of the control inside the shadow
root, resolved relative to that root. Ids inside a shadow root are scoped to it,
so a positional path is usually the only addressing that works there, and the
host is the stable handle.

A frame token wraps the frame element's own selector, so a reader can find the
frame as well as the field inside it. Nested boundaries repeat: a control two
frames deep reads `frame[#a] >> frame[#b] >> #card`, and two shadow roots deep
reads `#outer >>> #inner >>> input:nth-of-type(1)`.

Neither separator is valid CSS. That is deliberate. A selector that crossed a
boundary and still looked like plain CSS would be pasted into DevTools, return
nothing, and read as a defect in the tool rather than as a boundary in the page.

### Blind spots have selectors too

Some descriptors name a control the extractor knows is there and cannot read.
They carry an `undetectable_reason`, and their selector points at the thing that
blocked the read rather than at the control itself.

| Reason | Selector points at | Cause |
|---|---|---|
| `closed-shadow-root` | the custom element host | The component's shadow root is closed. |
| `cross-origin-frame` | the frame token, for example `frame[#hosted-card]` | The frame's document cannot be reached from the page. |
| `canvas-region` | the canvas element | The page yielded no controls at all and holds a large canvas. |

A hosted payment field behind a cross-origin frame is common and correct, so the
finding P3 raises from it should say so rather than imply a defect.

### Stability

Selectors are stable across runs of the same page, and the fixture expectations
under `tests/fixtures/extract/expected/` are golden files that turn any change
to them into a reviewable diff.

What can legitimately change a selector is a change to the page: adding an id
where there was none moves a control from rank 3 to rank 1, and adding a second
control with the same name moves one from rank 2 to rank 3. That is the notation
being honest about the page rather than instability in the tool.

---

## Finding catalogue

Written at P3, with the audit engine, the fix templates, and the decision
procedure. Each entry will name its severity, the conditions that raise it, the
fix text it emits, and the taxonomy labels that can produce it.
