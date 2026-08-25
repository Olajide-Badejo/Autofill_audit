# Findings

This document has two halves.

The **selector contract** below is written at P2 and is stable from now on. It
is the notation every finding, every report renderer, and every answer key uses
to name a form control, and spec section 9.3 requires it to be stated exactly
once and used identically by all three renderers. This is that once.

The **finding catalogue** is written at P3, together with the audit engine that
raises them and the fix templates that resolve them. It is the second half of
this document, and it starts at [the catalogue](#finding-catalogue).

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

The catalogue is closed. There are fifteen codes, they are the fifteen of spec
section 11.1, and a sixteenth is a change to the specification rather than an
addition to a list. A code is a promise that a class of problem has a defined
trigger, a defined severity, and a defined fix; adding one without all three is
how a finding list turns into a list of opinions.

Every entry below is generated from the same place the tool reads it,
[`src/autofill_audit/audit/findings.py`](../src/autofill_audit/audit/findings.py),
where the severities and the fix templates live beside the enum. **Fix text is
data, not strings scattered through the renderers**, which is what makes the
terminal, JSON, and HTML reports agree by construction rather than by three
people remembering to make the same edit.

### Severities, and what the exit code does with them

| Severity | Means | Counts towards `--fail-on` |
|---|---|---|
| `critical` | Autofill will certainly fail on a field a user must fill | `critical`, `warning`, `info` |
| `warning` | Autofill will probably fail, or fill wrongly | `warning`, `info` |
| `info` | Works, but is fragile or non-ideal | `info` |
| `note` | Informational, no action implied | never |

Nothing above `info`, which is to say no `warning` and no `critical`, may fire on
a correctly built page. That is not a hope: it is a property test over the whole
clean-quality slice of the corpus, it is a phase gate, and it is the single check
that decides whether this tool is worth installing. A missed finding costs a
developer a broken field they were going to find anyway. A wrong one costs them
an afternoon and costs this project its credibility.

### The codes

Each entry gives the trigger, the fix template as it is stored, and a worked
example: the markup that raises it, and the markup that resolves it.

---

#### `MISSING_AUTOCOMPLETE` (critical)

**Trigger.** Nothing is declared, and the inferred label is an autofillable token
at or above the high-confidence threshold.

**Fix template.** `add autocomplete="{label}" to {selector}`

```html
<!-- before -->
<label for="ck-email">Email address</label>
<input id="ck-email" name="ck_email" type="text">
```
```
#ck-email  MISSING_AUTOCOMPLETE
           add autocomplete="email" to #ck-email
           evidence: declaration:absent, label:email-words [rule tier HIGH]
```
```html
<!-- after -->
<label for="ck-email">Email address</label>
<input id="ck-email" name="ck_email" type="email" autocomplete="email">
```

Note that `autocomplete="on"` reaches this branch too. It is a valid value, and
it names no field, so a browser learns nothing from it that it did not already
guess. The decision procedure of spec section 11.2 routes a null token here on
purpose.

---

#### `WRONG_AUTOCOMPLETE` (critical)

**Trigger.** The declared token differs from the inferred label, the inference is
at or above the high-confidence threshold, and the two are not in the documented
equivalence set below.

**Fix template.** `{selector} declares autocomplete="{declared}" but looks like
{label}; change to autocomplete="{label}"`

```html
<!-- before -->
<label for="ck-holder">Name on card</label>
<input id="ck-holder" name="ck_holder" autocomplete="name">
```
```
#ck-holder  WRONG_AUTOCOMPLETE
            #ck-holder declares autocomplete="name" but looks like cc-name;
            change to autocomplete="cc-name"
```
```html
<!-- after -->
<label for="ck-holder">Name on card</label>
<input id="ck-holder" name="ck_holder" autocomplete="cc-name">
```

`name` fills the person's own name and `cc-name` fills the name printed on the
card. They are usually the same string and they are not the same field, and a
browser filling a saved profile into a payment form gets this wrong.

**This finding is asymmetric on purpose.** A declaration is authoritative unless
the tool is confident it is wrong. The developer stated an intent in the markup;
a mid-confidence classifier disagreeing with a stated intent is not evidence, it
is noise, and a tool that emitted it would be loudest on the pages that are most
nearly correct.

---

#### `OFF_SPEC_TOKEN` (critical)

**Trigger.** An `autocomplete` value is present and does not name exactly one
field-name token that the HTML specification defines. Four shapes reach it: a
token nobody defines, modifiers with no field name, an attribute present but
empty, and two field names at once.

**Fix template.** `autocomplete="{declared}" is not a valid autofill token; use
"{label}"`

```html
<!-- before -->
<label for="ck-postcode">Postcode</label>
<input id="ck-postcode" name="ck_postcode" autocomplete="zipcode">
```
```
#ck-postcode  OFF_SPEC_TOKEN
              autocomplete="zipcode" is not a valid autofill token;
              use "postal-code"
```
```html
<!-- after -->
<label for="ck-postcode">Postcode</label>
<input id="ck-postcode" name="ck_postcode" autocomplete="postal-code">
```

**A WHATWG token this project's taxonomy leaves out is not off specification.**
Spec section 7.1 excludes `address-level3`, `impp`, the `bday-*` parts and about
a dozen others from the *label* set, because law 2's reachability rule cannot be
satisfied for them. That is a statement about what the classifier may predict,
not about what HTML permits. A page declaring `address-level3` has declared
something valid, and the audit engine says nothing about it at all: it has no
label to compare against, so it makes no claim.

---

#### `AUTOCOMPLETE_OFF` (warning)

**Trigger.** `autocomplete="off"` on a field inferred to be a personal-data
field.

**Fix template.** `remove autocomplete="off" from {selector}; browsers may ignore
it and users lose autofill`

```html
<!-- before -->
<label for="ck-phone">Phone number</label>
<input id="ck-phone" name="ck_phone" type="tel" autocomplete="off">
```
```html
<!-- after -->
<label for="ck-phone">Phone number</label>
<input id="ck-phone" name="ck_phone" type="tel" autocomplete="tel">
```

On a search box or a one-time code this is correct markup and nothing is
reported, because the branch tests whether the inferred label is personal data
before it fires.

---

#### `UNLABELED_FIELD` (warning)

**Trigger.** No `<label for>`, no ancestor `<label>`, no `aria-label`, and no
`aria-labelledby`.

**Fix template.** `add a <label for="{id}">...</label> to {selector}`

```html
<!-- before -->
<input name="ck_addr" type="text">
```
```html
<!-- after -->
<label for="ck-addr">Street address</label>
<input id="ck-addr" name="ck_addr" type="text" autocomplete="street-address">
```

A `title` attribute is deliberately not one of the four. It is a tooltip: it is
announced inconsistently, it is invisible on touch, and spec section 11.1 names
four sources and stops.

---

#### `PLACEHOLDER_AS_LABEL` (warning)

**Trigger.** A placeholder is present and is the only text signal.

**Fix template.** `{selector} uses a placeholder as its label; add a real
<label>`

```html
<!-- before -->
<input id="input7" placeholder="Full name">
```
```html
<!-- after -->
<label for="ck-name">Full name</label>
<input id="ck-name" name="ck_name" placeholder="Ada Lovelace" autocomplete="name">
```

A placeholder disappears the moment somebody types, which is exactly when a user
most needs to know what they are typing. This and `UNLABELED_FIELD` are mutually
exclusive: they are two names for one problem and a report that made both would
be a report whose counts nobody could reconcile.

---

#### `SPLIT_FIELD` (warning)

**Trigger.** A detected split expiry pair where either member lacks the matching
declaration. Raised **once per group**, never once per member.

**Fix template.** `{selector} is one half of a split expiry; set
autocomplete="{month_token}" and "{year_token}" on the pair`

```html
<!-- before -->
<select id="ck-mm" name="ck_mm">...twelve months...</select>
<select id="ck-yy" name="ck_yy">...a run of years...</select>
```
```html
<!-- after -->
<select id="ck-mm" name="ck_mm" autocomplete="cc-exp-month">...</select>
<select id="ck-yy" name="ck_yy" autocomplete="cc-exp-year">...</select>
```

Once per group because the fix changes both halves together. Telling a reader
twice is telling them to do the job twice.

---

#### `COMPOSITE_FIELD` (warning)

**Trigger.** The inferred label is the composite extra, and no declaration names
the token the composite should carry.

**Fix template.** `{selector} collects several values in one control; declare
autocomplete="{label}" or split it`

```html
<!-- before -->
<label for="ck-exp2">Expiry (MM/YY)</label>
<input id="ck-exp2" name="ck_exp2" maxlength="5">
```
```html
<!-- after -->
<label for="ck-exp2">Expiry (MM/YY)</label>
<input id="ck-exp2" name="ck_exp2" maxlength="5" autocomplete="cc-exp" inputmode="numeric">
```

Which token a composite should carry depends on what it composites: a short
control beside a card number takes the combined expiry token, and a textarea
takes the street-address token. A composite that already declares the right one
is correctly built and nothing is reported.

---

#### `GENERIC_IDENTIFIER` (info)

**Trigger.** The `name` or `id` matches the generic pattern set, and no label
exists.

**Fix template.** `give {selector} a meaningful name/id, or declare autocomplete`

```html
<!-- before -->
<input id="input7" name="field_7">
```
```html
<!-- after -->
<label for="ck-name">Full name</label>
<input id="ck-name" name="ck_name" autocomplete="name">
```

The pattern set is narrow: a run of digits after `input`, `field`, `txt`, or
`ctl`, or a long hexadecimal run. A wider test flags ordinary short identifiers,
and a check that cries wolf is a check somebody disables.

---

#### `WRONG_INPUT_TYPE` (info)

**Trigger.** The inferred label implies a `type` or `inputmode` the control
lacks.

**Fix template.** `set {attribute}="{expected}" on {selector}`

```html
<!-- before -->
<label for="ck-email">Email address</label>
<input id="ck-email" type="text" autocomplete="email">
```
```html
<!-- after -->
<label for="ck-email">Email address</label>
<input id="ck-email" type="email" autocomplete="email">
```

**`postal-code` is deliberately absent from this table.** Spec section 11.1 gives
its expected inputmode as "per locale" and it is right to: a German or American
postal code is digits and wants a numeric keypad, while a British, Irish,
Canadian, or Dutch one contains letters and would be made harder to type by one.
Nothing on a field descriptor names the country the form is for, so this table
stops where the evidence stops.

---

#### `MISSING_NAME_ATTR` (info)

**Trigger.** A control inside a `<form>` carries no `name` attribute.

**Fix template.** `add a name attribute to {selector}`

A control with no name is not submitted, so this is usually a bug in the form
rather than only an autofill problem. It is `info` rather than higher because a
page using JavaScript to collect values does not need one.

---

#### `LOW_CONFIDENCE` (note)

**Trigger.** Nothing is declared and the inference sits between the low and high
thresholds.

**Fix template.** `{selector} may be {label} ({confidence}); declare autocomplete
explicitly`

```
form[name="checkout"] [name="ck_q1"]  LOW_CONFIDENCE
  may be organization (rule tier LOW); declare autocomplete explicitly
  evidence: declaration:absent, context:organization-words [rule tier LOW]
```

This is the near-miss band. Its purpose is to surface what the tool nearly said,
not to be right, and it never counts towards a failing exit code.

---

#### `UNDETECTABLE_FIELD` (warning)

**Trigger.** The descriptor names a blind spot: a closed shadow root, a
cross-origin frame, or a page whose only form-like element is a canvas.

**Fix template.** `{reason}: autofill cannot see this field; expose it in light
DOM or declare autocomplete on the host`

**One reason has its own text, and the difference matters.** A hosted payment
field behind a cross-origin frame is common and correct, and spec section 9.6
requires the finding to say so rather than to imply a defect:

```
frame[#hosted-pan]  UNDETECTABLE_FIELD
  the control is inside a cross-origin frame, which is how hosted payment
  fields are built on purpose; this is not necessarily a defect. Autofill
  still works inside the frame, and the frame's own document is where its
  autocomplete attributes belong. Audit that document separately
```

For a closed shadow root the general template is right, and the fix is to declare
the token on the host element or to reopen the root.

---

#### `EXTRACTION_INCOMPLETE` (info)

**Trigger.** The extraction budget expired with the DOM still mutating.

**Fix template.** `the page was still adding fields when auditing stopped; re-run
with a longer --settle`

This is a fact about the run rather than about the markup, and it is reported so
that a short field list is never mistaken for a complete one.

Two other page-level facts the extractor reports, a truncated walk and an
unreadable frame, have no code in the catalogue and are printed as page notes
instead. The catalogue is closed at fifteen, so a fact with no code is reported
as a fact rather than given an invented one.

---

#### `KEY_MISMATCH` (note, never user-facing)

**Trigger.** Corpus mode only: the prediction differs from the answer key.

**Fix template.** `answer key says {expected}, {engine} predicted {label}
({confidence})`

The answer key never changes a user-facing finding. It produces these records on
a separate list, and keeping it out of the finding path is what makes the corpus
a test rather than an oracle the product depends on.

---

### Equivalence sets

Some declared and inferred disagreements are not errors. These are consulted
before `WRONG_AUTOCOMPLETE` fires. Omitting them would make the tool loudest on
the pages that are most nearly correct, which is the fastest way to get an
auditing tool uninstalled.

| Set | Why |
|---|---|
| `name` against `given-name` or `family-name` | A page that declares the whole name where this tool reads one half has made a defensible choice, and so has a page that does the reverse. Both fill correctly from a stored profile. |
| `tel` against `tel-national` | On a form with one telephone field they are the same field. |
| `country` against `country-name` | Which of the two a control wants is a fact about its option values, not about the field. |
| The composite extra against `cc-exp` or `street-address` | A single MM/YY input declaring `cc-exp` is correctly declared, and so is a full-address textarea declaring `street-address`. The extra label carries the structural fact, not a contradiction. |
| A split-expiry extra against `cc-exp-month` or `cc-exp-year` | The pair is still declared with the specification's own tokens; the extra exists to carry the fact that both halves must change together. |
| **Any declaration whose modifiers differ but whose token matches** | See below. |

The last one is not a pair of labels and so is not a table row. It is handled by
comparing the parsed **token** rather than the raw attribute: a declared
`shipping postal-code` carries the token `postal-code` and the modifier
`shipping` separately, so an inferred `postal-code` matches it exactly.

Spec section 7.1 is emphatic that getting this wrong produces a flood of false
criticals on precisely the well-built checkout pages that need them least. There
is a fixture for it, `tests/fixtures/checkout_modifiers.html`, whose every
declaration carries a modifier and whose correct report is empty, and a test
named after the rule.

### Confidence, and why it is a tier

The rule baseline has no probabilities. It reports one of four ordered tiers, and
every renderer shows the tier by name:

| Tier | Fires when | Band |
|---|---|---|
| `HIGH` | An intrinsic attribute or a real label matched | confident |
| `MEDIUM` | An identifier, a placeholder, or an option list matched | confident |
| `LOW` | Only surrounding context matched | near miss |
| `NONE` | Nothing matched, or every tier tied | silent |

The numbers behind the tiers are constants in one place,
[`classify/base.py`](../src/autofill_audit/classify/base.py), and they are **not
probabilities, not calibrated, and not measured**. Printing one of them as a
percentage would assert a frequency nothing in this project has observed. The
band mapping and the reasoning behind it are recorded in
[`audit/thresholds.json`](../src/autofill_audit/audit/thresholds.json), which the
runtime reads; P4 replaces the mapping with thresholds derived on the dev split
against a precision target committed before the measurement.

A tie is not a failure of the table. German writes one phrase for both a whole
street address and the first of several address lines, and a field labelled only
"Password" is a login field on one page and a registration field on the next. In
those cases the tier ties, the engine falls through, and if nothing else
distinguishes them the answer is `UNKNOWN` and no finding is raised. Guessing
would produce a confident instruction to write the wrong token into production
markup, which is what law 1 exists to prevent.

### Configuration

`autofill-audit.toml`, discovered upward from the working directory, or named
with `--config`. Precedence is command-line flag, then environment variable
(`AUTOFILL_AUDIT_*`), then this file, then the default.

```toml
# Defaults for this project.
engine = "auto"
format = ["terminal", "json"]
fail_on = "critical"

# Codes this project has decided not to act on. Each becomes a suppression.
ignore = ["GENERIC_IDENTIFIER"]

# A suppression scoped to one control. The reason is required.
[[suppress]]
code = "UNLABELED_FIELD"
selector = "#vendor-widget-input"
reason = "a third party widget whose markup we do not control"
```

**A suppression never deletes a finding.** It moves it to the `suppressed` key of
the JSON report with the reason attached, and the terminal report says how many
were suppressed. A finding that vanished without trace is how a config file
becomes a way to lie to your own CI, and the reason is required for the same
reason: a suppression nobody can review is a suppression nobody will.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Completed; nothing at or above the failure threshold |
| 1 | Completed; at least one finding at or above it |
| 2 | Usage error: bad arguments, unreadable file, unparseable config |
| 3 | The page could not be loaded, or extraction failed entirely |
| 4 | Internal error, which is a bug; prints a traceback and asks for an issue |

`--fail-on {critical,warning,info,never}` moves the threshold for code 1.

**Code 3 is deliberately distinct from code 1.** A pipeline has to be able to
tell "your form has problems" from "the auditor could not reach the page", and
collapsing them produces exactly the flaky red build that gets the check deleted.

### Which labels can produce which codes

Every label in the taxonomy can produce `MISSING_AUTOCOMPLETE`,
`WRONG_AUTOCOMPLETE`, and `LOW_CONFIDENCE`, except the two that name an absence:

- `UNKNOWN` produces `UNLABELED_FIELD` when nothing labels the control, and
  otherwise produces nothing at all. It never produces a confident claim.
- `NOT_AUTOFILLABLE` produces no primary finding by construction. Without it the
  engine would tell a developer to put `autocomplete` on their search box.
- `COMPOSITE_UNSPLIT` produces `COMPOSITE_FIELD` in place of
  `MISSING_AUTOCOMPLETE`.
- `CC_EXP_SPLIT_MONTH` and `CC_EXP_SPLIT_YEAR` produce `MISSING_AUTOCOMPLETE`
  naming the specification's own month and year tokens, and additionally
  `SPLIT_FIELD` once for the pair.

The structural codes, `UNLABELED_FIELD`, `PLACEHOLDER_AS_LABEL`,
`GENERIC_IDENTIFIER`, `MISSING_NAME_ATTR`, `SPLIT_FIELD`, `UNDETECTABLE_FIELD`,
and `EXTRACTION_INCOMPLETE`, do not depend on what the control means and can fire
alongside any label. They carry structural evidence and the word `structural`
where a confidence would go, because there is no classification to be confident
about: the control has no label, or it has not, and that is either true or false.
