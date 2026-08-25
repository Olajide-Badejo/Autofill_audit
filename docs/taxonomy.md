# The label taxonomy

The label space is the WHATWG HTML autofill field-name token set plus five
enumerated extra labels. It has exactly one definition in code,
[`src/autofill_audit/taxonomy.py`](../src/autofill_audit/taxonomy.py), and every
rule table, training script, report renderer, and test imports it from there
(ground rule 6). A label string written anywhere else in `src/` or `scripts/`
fails `scripts/check_reachability.py`, which runs in CI.

## Why this vocabulary

A classifier's label space determines what its output can be used for. Had this
project invented labels such as `POSTCODE` or `ZIP`, every finding would need a
translation step from internal label to actionable advice, that translation
would be a second undertested mapping, and the tool's central claim (*here is
the exact attribute value to add*) would sit one indirection away from the
model's actual output.

Taking the specification's tokens directly means **the label is the fix**:
predict `postal-code`, emit `add autocomplete="postal-code"`.

It also settles a hundred small design arguments for free. Whether address lines
are one label or three, whether card expiry is one field or two, whether a phone
country code is separable: all already decided, by a standards body, in public.
Adopting an existing vocabulary is cheaper than defending a new one.

## The specification tokens

Tokens are lowercase and hyphenated exactly as the specification writes them,
because the label is the fix string. Grouped here for human comprehension; in
code they are one enum plus a group mapping.

**Identity.** `name`, `given-name`, `additional-name`, `family-name`,
`honorific-prefix`, `honorific-suffix`, `nickname`

**Contact.** `email`, `tel`, `tel-country-code`, `tel-national`,
`tel-extension`, `url`

**Address.** `street-address`, `address-line1`, `address-line2`,
`address-line3`, `address-level2`, `address-level1`, `postal-code`, `country`,
`country-name`, `organization`

**Payment.** `cc-name`, `cc-number`, `cc-exp`, `cc-exp-month`, `cc-exp-year`,
`cc-csc`, `cc-type`, `transaction-amount`

**Credentials and other.** `username`, `new-password`, `current-password`,
`one-time-code`, `bday`, `sex`

### What is deliberately excluded

The full specification list is longer. The remaining tokens (`address-level3`,
`address-level4`, `photo`, `impp`, `language`, the finer-grained `tel-*`
decomposition, `transaction-currency`, `organization-title`, and the `bday-*`
parts) are excluded from the initial set because the reachability rule below
cannot be satisfied for them: they do not occur in the form families being
generated, so no answer key would emit them, so no test could exercise them.

They are candidates for growth, not omissions. A label that exists in the enum
but is emitted by nothing is dead weight that inflates the denominator of every
macro-averaged metric, which is precisely how a project accidentally reports a
worse F1 than it earned, or a better one, depending on which direction the dead
label falls.

### Modifiers are not labels

`shipping`, `billing`, `home`, `work`, `mobile`, `fax`, `pager`, `section-*`,
and `webauthn` are prefixes and qualifiers within an `autocomplete` value, not
field types. The extractor parses them out of a declared value and records them
on the descriptor; the audit engine uses them, so that a `shipping postal-code`
declaration matching an inferred `postal-code` is a match rather than a
mismatch; and the classifier never predicts them.

Getting this wrong produces a flood of false `WRONG_AUTOCOMPLETE` findings on
exactly the well-built checkout pages that need them least. Corpus answer keys
therefore carry `expected_modifiers` per field, so the behaviour is testable
from P3 rather than assumed.

## The extra labels

Five, enumerated, closed except by the growth rule.

| Label | Meaning | Why it exists |
|---|---|---|
| `UNKNOWN` | A control whose semantic type could not be determined above threshold | Law 1's escape hatch. Predicting `UNKNOWN` is a legitimate, correct answer and is scored as one. The hostile tier emits one deliberately undeterminable control per form so the label is reachable by something a human could not label either. |
| `NOT_AUTOFILLABLE` | A control that is correctly not an autofill target: search boxes, quantity spinners, comment textareas, coupon codes, consent checkboxes | Without it the model must assign a personal-data label to every field, and the audit engine would flag every search box on the web. This is the single highest-volume real-world label, and the corpus reflects that. |
| `CC_EXP_SPLIT_MONTH` | Card expiry month rendered as a `<select>` in a two-select pair | The specification's `cc-exp-month` is correct for these, but the *finding* differs: the fix must address both selects together, and the pairing is a structural fact the extractor detects rather than a semantic one the classifier infers. |
| `CC_EXP_SPLIT_YEAR` | The year half of the same pair | As above. |
| `COMPOSITE_UNSPLIT` | One control collecting what the specification splits, such as a single MM/YY text input or one full-address textarea | Produces a distinct finding with a distinct fix, and is common enough in the wild to be worth naming rather than mapping onto the nearest token. |

The two `CC_EXP_SPLIT_*` labels are the only place structure and semantics are
entangled in the label space, and that entanglement is deliberate rather than
accidental: the pair is exactly the case browser vendor guidance calls out, and
collapsing it to `cc-exp-month` would lose the information the fix needs.

### Labels are not roles

A control's ground-truth label is not the same thing as what a correct page
declares on it, and neither is the same as the semantic role the generator
composed the form from. `src/autofill_audit/corpus/roles.py` keeps the three
apart, because three cases make the distinction load bearing:

- Several roles share one label. A card expiry month as one half of a two-select
  pair and the same month as a lone text input are different page facts with
  different fixes.
- One label covers many unrelated roles. Every search box, quantity spinner,
  coupon field, comment area, and consent checkbox is `NOT_AUTOFILLABLE`.
- The label a correct page declares is not always the label the key records. A
  single MM/YY input is `COMPOSITE_UNSPLIT`, and its correct declaration is
  `cc-exp`. A full-address textarea is also `COMPOSITE_UNSPLIT`, and its correct
  declaration is `street-address`. The label alone cannot settle it; the role
  can.

## The growth rule

A label may be added if and only if, **in the same pull request**:

1. It is a token from the WHATWG list, or an extra label with a written
   justification in this document explaining why no existing token covers the
   case.
2. At least one corpus template emits it in its answer key, in at least two
   locales and at least two markup tiers.
3. The rule baseline has at least one rule producing it, *or* this document
   records why it is model-only and the training split contains at least a
   stated minimum count of examples.
4. At least one test asserts an end-to-end finding that depends on it.
5. `docs/findings.md` states which finding codes it can produce and what the fix
   text is.

`scripts/check_reachability.py` checks clauses 1 to 4 mechanically by
cross-referencing the taxonomy, the generated answer keys, the rule table, and a
pytest collection of label-tagged tests. It runs in CI and it is allowed to fail
the build.

Clause 2 is satisfied structurally by the generator rather than per label: every
template is instantiated in every locale and every tier, so a label emitted by
any template is emitted in six locales and four tiers by construction.

### What is enforced today

| Clause | Enforced | By |
|---|---|---|
| (a) token or enumerated extra | yes | `check_taxonomy_populated`, `check_groups_partition`, `check_no_duplicate_label_values` |
| (b) emitted by at least one answer key | yes, from P1 | `check_corpus_reachability`, which reads the committed sample corpus and generates a fresh grid |
| (c) reachable by a rule or present in training | not yet, P3 | listed in the script's `PENDING` |
| (d) asserted by at least one test | not yet, P3 | listed in the script's `PENDING` |

A clause moves out of `PENDING` and into `CHECKS` in the same commit that makes
it enforceable. A green run that silently claimed more than it checked would be
worse than an honest partial one.

## Locale provider status

Six locales: `en-US`, `en-GB`, `de-DE`, `fr-FR`, `ja-JP`, `en-NG`. The held-out
locale is `fr-FR` ([ADR 0005](adr/0005-held-out-locale.md)).

Spec section 8.2 asks for this table to be recorded rather than hidden, because
where a locale falls back to hand-authored data it is a real limitation of the
corpus and belongs in the write-up.

Faker provider availability was probed on the resolved Faker version at P1. The
result was better than the specification anticipated: **every one of the six
locales has a working Faker provider for names, streets, cities, administrative
areas, and companies**, including `en-NG`, which the orchestrator's plan
expected to be thin. `ja-JP` additionally provides the kana name providers the
Japanese templates need.

| Locale | Names, streets, cities, companies | Kana names | Labels, placeholders, identifiers | Phone numbers | Postal codes | Option lists |
|---|---|---|---|---|---|---|
| `en-US` | Faker | not applicable | hand authored | hand authored | hand authored | hand authored |
| `en-GB` | Faker | not applicable | hand authored | hand authored | hand authored | hand authored |
| `de-DE` | Faker | not applicable | hand authored | hand authored | hand authored | hand authored |
| `fr-FR` | Faker | not applicable | hand authored | hand authored | hand authored | hand authored |
| `ja-JP` | Faker | Faker | hand authored | hand authored | hand authored | hand authored |
| `en-NG` | Faker | not applicable | hand authored | hand authored | hand authored | hand authored |

Three columns are hand authored in every locale, for reasons that are not about
Faker's coverage:

- **Labels, placeholders, and identifiers.** Faker generates *values*, not the
  interface text a form shows. There is no provider that knows a German form
  says *PLZ* and names the field `plz`. These tables are the substance of the
  locale profiles and live in
  [`src/autofill_audit/corpus/locales/`](../src/autofill_audit/corpus/locales/).
- **Phone numbers.** Faker's phone providers emit numbers that look dialable.
  Ground rule 10 asks for values a reviewer can see are invented, so phone
  numbers come from a per-locale pattern instead. The `en-US` and `en-GB`
  patterns coincide with ranges published for fictional use; the others are
  hand-authored shapes and are not claimed to be reserved.
- **Postal codes.** Generated from a per-locale pattern so the *shape* is a
  locale fact under the generator's control, which is what the corpus needs to
  test, rather than a sample from a provider.

Card numbers come from the published payment-processor test set and from nowhere
else, so no generator path can emit a Luhn-valid live BIN.

### The locale profiles are structural

A generator that only swapped label strings across locales would produce a
corpus that tests translation rather than localisation, and the multilingual
claim would be untestable on it. The profiles therefore carry four kinds of
fact, and only the first is vocabulary.

| Locale | Address order | Administrative area | Postal code | Name split |
|---|---|---|---|---|
| `en-US` | lines, then city, state, ZIP on one row | State | always present, last | given then family |
| `en-GB` | lines, then town and county, then postcode | County | always present, last | given then family |
| `de-DE` | street, then postal code before town on one row | none | always present, before the town | given then family |
| `fr-FR` | street, then code postal before ville | none | always present, before the town | given then family |
| `ja-JP` | postal code first, then prefecture, municipality, street | Prefecture | always present, first | family then given, plus a kana pair |
| `en-NG` | lines, then city and state | State | frequently absent | given then family |

German and French address blocks carry no administrative-area field at all,
which is a fact about those forms rather than an omission. Nigerian postal codes
are frequently absent, expressed as a presence probability rather than a flat
absence, because "frequently" is the honest shape of that fact.

## Reporting minimum

A locale by tier cell needs a stated minimum number of fields before its
accuracy is reported as a percentage rather than as "insufficient data". The
constant lives in
[`src/autofill_audit/evaluate/metrics.py`](../src/autofill_audit/evaluate/metrics.py)
and the policy is recorded in [`report.md`](report.md). It is enforced by code
from P5 rather than left to whoever writes the table.

## The realised grid

Deliberately not repeated here. Spec section 8.5 says to record the realised
grid with its per-cell counts in the corpus manifest, and the generator writes
it to `corpus/manifest.json` on every run. Copying counts into prose would
create a second number to keep in agreement, and law 3 forbids a number in
`docs/` that does not trace to a committed result file.

Run `autofill-audit corpus validate` to print the label coverage table for a
corpus on disk.
