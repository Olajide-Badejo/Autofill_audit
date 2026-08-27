# Engineering log

Dated, append-only. Every gate, every surprise, every reverted decision. Written
as the work happens rather than reconstructed later, because the reports at P7
draw on this file and reconstruction from memory is both slower and less honest.

Newest entries go at the bottom.

## 2026-08-25: P0, foundations

### What was resolved

The toolchain matrix, in full, on the target machine. It is recorded in
[`adr/0001-toolchain-resolution.md`](adr/0001-toolchain-resolution.md) rather
than repeated here.

The headline is that the interpreter did not have to be held back. The
specification anticipated the four-way intersection of Playwright,
scikit-learn, onnxruntime, and the evaluation harness landing one CPython minor
behind the newest stable, since onnxruntime is usually the last of the four to
publish wheels. It did not: onnxruntime ships `cp314` wheels, so the pin is the
newest stable CPython and nothing was worked around.

Also resolved and recorded in the same ADR: click over typer, Make over just,
pip-compile over uv, and latexmk over tectonic. The last of these is the
specification's stated fallback condition rather than its stated preference, and
it applies because this machine already carries a full TeX Live installation.

### Surprises

**Passwordless sudo, so the Playwright dependency fallback was not needed.**
The specification plans for `playwright install chromium --with-deps` being
refused for lack of root, with a manual system library list recorded in
`environment.md` as the fallback. Root was available, the flag worked, and the
libraries installed cleanly. The fallback list is therefore deliberately *not*
written down: recording a list that was never exercised would invite somebody to
follow it later and install the wrong set.

**The evaluation harness is not on PyPI.** Discovered while deciding whether to
put it in `pyproject.toml` at P0. It exists only as a GitHub repository. Since
tagging a stable release here is forbidden while any dependency is a git
reference, publishing it is a blocking cross-repo task rather than a detail, and
it is filed as such in [`cross-repo-tasks.md`](cross-repo-tasks.md) with status
open. The dependency is deliberately absent from `pyproject.toml` until P5, so
that the lock file does not carry something nothing imports.

**The dash check had to be written so it could survive itself.** The first draft
of `scripts/check_dashes.py` declared its two forbidden characters as string
literals, which made the file an immediate violation of the rule it enforces.
They are now built with `chr()`. The same reasoning applies to
`scripts/check_commit_msg.py`, whose blocklist would otherwise have been the one
file in the repository carrying every string the repository forbids; its
patterns are stored base64 encoded and decoded at import. Two tests do the same
thing for the same reason. This is a small point but it is a real one: a checker
that cannot pass its own check is a checker that gets an exemption, and an
exemption is where enforcement starts to rot.

**Docstring-only placeholders had to be genuinely statement-free.** The module
skeleton was first written with `from __future__ import annotations` in every
placeholder. That is one executable statement per file, thirty of them, none
ever imported, which pushed measured coverage of the library well under the
gate for no reason connected to the code that actually exists. Stripping the
import leaves the placeholders with zero statements, which is what the coverage
gate should see: the phases that fill them bring their own tests.

### Decisions taken inside P0 that the specification left open

- **`requires-python` is `>=3.14`**, not a wider floor. It is the only
  interpreter CI exercises, and claiming support for versions nothing tests is
  the kind of small dishonesty that this project's laws exist to rule out.
  Widening it is a later decision that arrives with a CI matrix entry.
- **The reachability check does more than the task required.** Beyond the
  taxonomy self-consistency checks it also scans `src/` and `scripts/` for label
  strings written as literals outside the taxonomy module, which is ground rule
  6 made mechanical. The scan is limited at P0 to tokens that cannot be confused
  with ordinary prose, meaning the hyphenated specification tokens and the
  uppercase extras; `name`, `email`, `tel`, and `url` are excluded because a
  check that cries wolf is a check somebody turns off.
- **The traceability check states its rule positively.** Rather than flagging
  every numeric literal and then excusing most of them, it flags three
  measurement shapes: a percentage, a probability-shaped decimal, and a number
  sharing a line with a measurement word. Years, ISO dates, version strings,
  reference numbers, list markers, code blocks, and URLs are never flagged at
  all. A line is cleared either by a result-file reference or by an explicit
  annotation carrying a written reason. The alternative design, flag everything
  and maintain an exclusion list, was rejected because the exclusion list grows
  until the check means nothing.

### Deviations from the build specification, recorded rather than absorbed

- **`report_for_me/` is local only and is gitignored.** The specification lists
  the personal archival report as a committed deliverable, source and PDF both.
  The author's instruction overrides that: it is written for the author, with
  the context gone, and it stays on the machine. The other two reports, the
  public main report and the debug report, are unaffected and are still
  committed at P7. Noted here because a reader of the definition-of-done
  checklist would otherwise find one box that can never be ticked.
- **A first remote was created and then abandoned.** The repository was
  initially pushed to a remote whose name differed in case and separator from
  the one the author wanted. The remote was repointed before any run URL was
  recorded, so nothing in `ci-proof.md` refers to the abandoned repository. The
  abandoned one is left in place rather than deleted, because the credentials in
  use do not carry delete scope.

### Gates

Recorded here as they were run, with the CI run links in
[`ci-proof.md`](ci-proof.md).

- Local gates: `make gates`, which is ruff check, ruff format, the dash check,
  mypy strict, pytest with the coverage gate, reachability, and traceability, in
  the order CI runs them. All green. Measured library coverage came out at the
  ceiling, which is unsurprising when the library is a taxonomy, a small CLI,
  and a set of statement-free placeholders.
- Wheel and sdist built, the wheel installed into a pipx environment of its own,
  and the installed command run.
- All six CI jobs green on `main`.
- All six CI jobs observed red, one per scratch branch, each from a single
  deliberate change, with the run links and the failure text recorded. Branches
  deleted afterwards.

Two things came out of the proof-of-failure exercise that were worth having.
The build job's first attempt was itself broken: it assumed pipx would place
the console script at a fixed path, which is a guess and was wrong on the
runner. The job now sets its own pipx home and bin directory, which both fixes
the assumption and gives the wheel a genuinely clean environment to install
into. Separately, the deliberate taxonomy breakage failed both the reachability
job and the test job, which is the correct outcome: the property is asserted in
two independent places on purpose, and a defect that only one of them noticed
would mean the other was not doing its job.

### What P1 needs to know

- The taxonomy is complete and frozen at the specification's token set plus the
  five extras. `GROUPS` partitions it. Import everything from
  `src/autofill_audit/taxonomy.py` and nowhere else, because the reachability
  check now fails the build on a label string written anywhere else in `src/` or
  `scripts/`.
- `scripts/check_reachability.py` is written to be extended rather than
  rewritten: add a function returning a `CheckResult` and register it in
  `CHECKS`. The three clauses that are not yet enforceable are listed in
  `PENDING`, each naming the phase that activates it. Move a clause out of
  `PENDING` and into `CHECKS` in the same commit that makes it enforceable.
- The corpus directory is gitignored except for the sample corpus and the
  manifest. The ignore rules for those exemptions are already in `.gitignore`.
- The lock file is regenerated only by `make lock`, as its own commit with a
  changelog note.
- Faker is a `dev` dependency, not a runtime one. The generator runs from a
  checkout, never from an installed wheel, which is why it does not need to be.

## 2026-08-25: P1, taxonomy and corpus

### Faker becomes a runtime dependency, reversing a P0 note

P0 closed with the note that Faker is a `dev` dependency because "the generator
runs from a checkout, never from an installed wheel". That was wrong, and the
error only becomes visible once the command surface of spec section 14 is
actually wired up: `autofill-audit corpus generate` is a documented subcommand
of the shipped console entry point. A documented command that raises an import
error on a `pipx`-installed wheel is worse for a user than one extra dependency
is for the wheel, and the alternative (a lazy import with a graceful refusal)
buys a smaller wheel at the cost of a code path that only ever runs on a
misconfigured install.

Faker moves to the runtime dependency set. `make lock` was run afterwards, per
spec section 18, and produced a byte-identical lock file: the lock is compiled
with the `dev` extra already, so it carried Faker at this exact pin, and
pip-compile annotates both cases as `via autofill-audit (pyproject.toml)`. There
is therefore no lock commit, which is the right outcome rather than a skipped
step, since regenerating a lock that does not change should not create one.

### The corpus design as built

The template is the atom of the split, so the template had to become the atom of
the generator too. Five families, five structurally distinct templates each,
instantiated across six locales and four tiers. A template asks for a name block
or an address block *by style*; the locale profile decides which slots that
style expands to and in what order. A template that listed address line one and
address line two directly would silently assert that every locale composes an
address the same way, which is the failure spec section 8.1 names.

The locale profiles are the substance of the phase. Each carries label,
placeholder, and identifier strings; which slots exist; what order they appear
in; and how names decompose. German and French address blocks carry no
administrative-area field at all. Japanese leads with the postal code and adds a
kana name pair. Nigerian postal codes are frequently absent, expressed as a
presence probability rather than a flat absence, because "frequently" is the
honest shape of that fact.

### Surprises

**Faker covered every locale, including the one the plan expected to be thin.**
The orchestrator's plan anticipated hand-authored fallback tables for `en-NG`.
The probe at the top of the phase found working providers for names, streets,
cities, administrative areas, and companies in all six locales, and the kana
name providers Japanese needs. The hand-authored tables still exist and still
matter, but for a different reason than expected: Faker generates values, not
interface text, and no provider knows that a German form says *PLZ* and names
the field `plz`. That table is the locale profile, and it was always going to be
hand written. The status table in `taxonomy.md` records what came from where.

**A module named `locales.py` shadowed the `locales/` data directory.** Spec
section 6 names the data directory `locales/`, and the obvious name for the
module that loads it was `locales.py` beside it. Importing
`autofill_audit.corpus.locales` then resolves to the module, and
`resources.files` on it walked one level too high and looked for the tables in
the package root. The module is `profiles.py` now, the directory keeps the name
the specification gives it, and the reason is recorded in the module docstring
so nobody renames it back.

**A dataclass with a parent pointer cannot have a generated `__eq__`.** The
small HTML tree used to check selectors gave every element a `parent`, and
`list.index` during `:nth-of-type` resolution compared two elements, which
recursed up and down the tree until the stack ran out. Elements are identity
objects; `eq=False` is the fix and the docstring says why.

**The mixed tier could produce a form with no clean section.** The draw forces
at least one hostile section and at least one clean one. The clean pass looked
for a section that was not hostile, and when every section had drawn hostile
there was no such candidate, so it silently did nothing and the form came out
uniformly hostile under a mixed label. It surfaced on two templates out of
twenty-five, which is exactly the frequency at which a defect gets shipped. A
section may now be promoted to clean unless it is the only hostile one, and
because a template is required to carry at least two sections there is always a
legal choice. The parametrised test covers all twenty-five templates rather than
a sample, which is how it was caught.

**A shared Faker instance was a latent determinism defect.** The first
implementation cached one Faker per locale and reseeded it per form, which is
safe only while exactly one value provider is alive at a time. Nothing in the
current call path breaks that, which is what made it dangerous: it would have
broken the same-seed-same-bytes rule silently, the first time a caller built two
forms at once.
Constructing a Faker costs well under a millisecond, so each provider now owns
one and the whole grid pays a fraction of a second for an invariant that cannot
be broken from outside. Found by a test asserting that two providers built with
the same seed produce the same value, which they did not.

### Decisions worth recording

**The per-form seed includes the template id.** Spec section 8.1 writes the axis
tuple as family, locale, tier, variant. With five templates per family, two
templates of one family at the same locale, tier, and variant would draw the
same seed and therefore the same sample values. The template id joins the digest
input and the family stays in it, so the input is a superset of the
specification's rather than a replacement.

**The expiry year window is an explicit input, not the clock.** A card expiry
select has to offer years near the present, and spec section 9.5 has the
extractor detect the pair against the current year, so a hardcoded window would
expire. The base year is a generator argument defaulting to the current year and
recorded in the manifest. The corpus is a deterministic function of the seed and
the base year together, and passing the manifest's base year back reproduces the
bytes exactly, indefinitely. The reachability check and the committed sample
both pin it, so neither goes red when the year turns.

**Held-out-locale forms of training templates go to a fourth partition.** The
specification leaves this open. A French form whose template is in train cannot
go to train, because the locale is held out, and must not go to dev or test,
because its template is a training template and that would leak the convention
the split exists to separate. It goes to `excluded`: generated, recorded, and
used by nothing. The reported unseen-locale slice is the French forms in dev and
test, which are clean on both axes.

**The second selector preference uses a descendant combinator.** Spec section
9.3 sketches it as `form[name] > [name="..."]`. A literal child combinator only
matches a control that is an immediate child of the form element, and every form
this generator emits wraps controls in layout containers, so it would produce
selectors that resolve to nothing. The deviation is recorded in
`selectors.py` and in the notes for P2, because the extractor has to reproduce
this exactly rather than approximately.

**Selector resolution is checked without a browser.** An answer key whose
selectors do not resolve is worse than no answer key: every downstream
measurement silently loses the fields it could not find, and the loss looks like
a classifier failure. P2 has a browser; requiring one here would couple P1's
gate to P2's dependency and stop the reachability job from being able to check
anything. The subset of CSS this generator emits is small and fully known, so
`domcheck.py` resolves exactly that subset and raises on anything else, rather
than quietly returning no match for syntax it does not understand.

**Faker moved to the runtime dependency set**, reversing a P0 note, because
`corpus generate` is part of the shipped command surface. Recorded at the top of
this entry.

### Gate

- `corpus generate --seed 20260825 --out corpus/` run twice, `diff -r` of the
  two outputs empty. Shown in the phase output.
- Realised grid: five families of five templates, six locales, four tiers, one
  variant. Well above the floor spec section 8.5 sets. Counts are in
  `corpus/manifest.json`, not repeated here, per spec section 8.5 and law 3.
- `corpus validate` green over the full generated corpus, over the committed
  sample, and over a narrow corpus in the test suite. Every key validates
  against the committed schema.
- Every label in the taxonomy is emitted by at least one answer key. The
  coverage table prints with nothing missing.
- `check_reachability.py` green with clause (b) active. It left `PENDING` in the
  commit that made it enforceable, per the P0 handoff.
- `make gates` green: ruff, the dash check, mypy strict, pytest with the
  coverage gate, reachability, traceability. Library coverage is comfortably
  above the gate.

### What surprised me about the hostile tier

It is graded rather than uniformly impossible, and that turned out to matter
more than expected. Half its controls carry the label text as a placeholder,
which is the placeholder-as-label antipattern and is genuinely classifiable. The
other half carry no text signal at all and leave only the identifier, which is
where the cross-locale claim is actually tested, since the identifiers are
localised. One control per form is deliberately undeterminable, and predicting
`UNKNOWN` on it is the correct answer rather than a failure. If every hostile
control were equally hopeless the tier would measure nothing except that the
tier is hard.
---

## 2026-08-25: P2, the extractor

The phase that turns a page into `list[FieldDescriptor]`, which spec section 5.1
makes the only interface anything downstream sees. A classifier never sees the
DOM and never sees an answer key; it sees a descriptor. Everything below is in
service of that boundary being real rather than aspirational.

### Where the work was put, and why it was put there

The traversal script reads the DOM and returns plain JSON. Everything after that
is Python over those records, and `descriptors_from_roots` is the seam: it takes
the same records a browser would have produced and does the rest with no browser
at all.

That split was the single most useful decision of the phase. Selector
generation, group detection, the honeypot rule, autocomplete parsing, and every
normalisation step are covered by tests that run in milliseconds, and the
browser-marked tests are left to prove the one thing only a browser can prove,
which is that a page really does say what the records claim. It also means the
coverage gate does not rest on Chromium being installed, which matters the first
time a Playwright upgrade goes sideways.

### The deviations, and the reasons

**Spec section 9.7's step order is contradictory, and the worked example settles
it.** The steps are numbered NFKC, casefold, de-camelCase, split, stoplist.
Taken literally, casefolding the whole string before looking for lower-to-upper
transitions destroys the information step 3 needs: `firstName` casefolds to
`firstname`, in which no boundary exists, and the specification's own worked
example (`firstName` becomes `first name`) becomes unreachable. The implemented
reading is NFKC, then boundary insertion, then casefold each resulting token.
Nothing step 2 exists for is lost, because casefold is applied to every token
and both properties the specification names it for are per character. What is
gained is that step 3 works at all.

**The stoplist has to be applied twice.** `ctl00` is the one entry on spec
section 9.7's list that names a real framework, and it cannot survive the
letter-to-digit split, which turns it into `ctl` and `00`. A stoplist applied
only after splitting would never match it anywhere. It is applied to the
delimiter-separated fragments first and to the finished tokens second, with one
list.

**Rank 2 of the selector order requires the name to be unique within the form.**
Not in the specification sketch, and it has to be there: every member of a radio
group shares one name, so without it a group of four radios gets one selector
four times. Recorded in `docs/findings.md`.

**The canvas rule fires only on the zero-control page.** P1's handoff left this
open, noting that the corpus has pages with plenty of controls *and* a canvas,
which is not the shape spec section 9.6 describes. Emitting a synthetic
descriptor for every large canvas would make every hostile checkout report one
more field than its answer key holds, and the reconciliation the gate asks for
would never balance. So a canvas is always recorded as a region, and the
page-level descriptor is emitted only when the page yielded no controls at all.
The information is there either way; what changes is whether it counts as a
field.

**Five signals from spec section 9.2 have no home in spec section 9.4.**
`minlength`, `multiple`, `step`, `min`, and `max` are collected because 9.2 says
to, and stop at the raw record because 9.4 is the fixed downstream contract that
every golden test will inherit. One of them, `multiple`, is genuinely used: a
multi-select with twelve options is a month picker to a careless detector and a
multiple-choice control to a careful one.

### What the browser actually does, which is not what I assumed

Playwright can evaluate inside a cross-origin frame. It drives each frame
through its own session, so the thing that makes a frame unreadable to this tool
is not Playwright failing; it is the page's own same-origin policy. The
accessibility test is therefore made from inside the parent document, by asking
for `contentDocument` in a try block, which is exactly the check a real script on
that page would make and exactly what spec section 9.6 means by "cannot be
accessed".

That also solved how to write the two frame fixtures offline. A `srcdoc` frame
inherits its parent's origin and so is same origin even under `file://`, where
two separate local files are opaque origins to each other and would not be. A
`data:` URL frame gets an opaque origin and so is unreadable. Both reproduce
with no network and no second server. Recorded in `docs/environment.md`.

### Bugs found by the tests rather than by me

**Hypothesis found the token splitter destroying combining marks.** The splitter
was built on Python's word class, which excludes combining marks, so every one
of them was treated as a separator. The failing case was the Turkish dotted
capital I: casefolding it yields an `i` followed by a combining dot, splitting on
that dot drops the dot, and a second pass over the same text returns something
different from the first. Idempotence is a property spec section 15 layer 4
requires, and it caught this in about two seconds.

The interesting part is what else the bug broke. Splitting on combining marks
shreds Devanagari, Thai, Hebrew with points, and anything in decomposed form. It
would never have shown up in this project's six locales, and it would have been
waiting for the first person to point the tool at a page outside them.

**The same property found a second, subtler one on the next run.** Case folding
does not always produce lowercase. Cherokee folds the other way, to uppercase,
so folding an `A` beside a Cherokee capital leaves a lowercase `a` next to an
uppercase letter: a case transition that the de-camelCase pass, which runs
before the fold, never saw. Feed the output back in and it splits into two
tokens, which is a different answer from the first.

The fix is to bracket the fold with boundary insertion rather than to run it
once before. Folding before the boundary pass is not an option, because that is
the original problem this module's docstring opens with, so the only order that
satisfies both constraints is to do it twice.

What made this one worth chasing rather than narrowing the strategy around: the
first instinct was to write the alphabet down to the six locales the corpus
covers and call idempotence a practical property. Both counterexamples were
outside those locales and both were real bugs, so the strategy went the other
way instead and now covers the whole basic multilingual plane. A brute-force
pass over every codepoint in it, alone and beside four different neighbours in
both orders, is clean.

**The duplicate-id fixture found a label attaching to the wrong control.** A
label's `for` attribute names one element, the one `getElementById` would return.
The first implementation mapped id to label and handed the same label to both
elements carrying a duplicated id, which is somebody else's label on a control
that has none.

### Constants, resolved

| Constant | Value | Reasoning |
|---|---|---|
| Load timeout | `15_000` ms | Generous, because a slow page is a real page. Bounded, because a page that never loads must not hang a CLI. |
| Network idle wait | `5_000` ms | Giving up on idle is not a failure. Plenty of healthy pages hold a socket open forever. |
| DOM quiet period | `250` ms | Longer than an animation frame, shorter than the gap a page leaves before injecting a field it means a user to see. |
| Settle budget | `3_000` ms | Total bound on the quiet stage, so an animation that mutates forever cannot hold it off. |
| Option truncation | `24` | Twice the largest option list this project reasons about. Spec section 9.4 gives the descriptor no field for the total option count, so the only way to tell a complete list of twelve months from the first twelve of five thousand branches is for the cut to fall where a meaningful list never reaches. |
| Max controls | `500` | Well above any real form. Reaching it is reported, never silent. |
| Canvas minimum area | `10_000` px squared | A hundred pixels square. Smaller canvases are sparklines and icons, and reporting those as possible hidden forms would teach a reader to skip the finding. |
| Frame depth | `8` | Three deep is an ordinary advertising stack; eight is pathological. |
| Expiry year window | `-5` to `+20` relative | Relative to a year the caller passes in, never to a literal, so nothing expires. Spec section 9.5 is explicit about this. |

### Gate

- Seventeen hand-authored fixtures, each with a header comment saying what it
  tests and a committed expected descriptor list, all matching. The thirteen
  spec section 15 layer 2 names, plus the cross-origin frame the gate requires
  an outcome for, the radio and checkbox groups the corpus does not emit, and
  the two malformed-markup pages.
- The four hard cases shown individually: closed shadow root, cross-origin
  frame, canvas, injected field.
- Full corpus sweep: every form, zero unhandled exceptions, controls found equal
  to answer-key entries, every injected control caught by the settle, every
  shadow-hosted control walked, every canvas region recorded.
- `make gates` green throughout: ruff, the dash check, mypy strict, pytest with
  the coverage gate, reachability, traceability.

### The one discrepancy, explained

The reconciliation compares selectors as a set, not as a list, and reports order
differences separately. An answer key lists its fields in the generator's slot
order, which appends a tier's extra controls to the end. The extractor returns
document order, which spec section 9.1 step 7 requires. Those agree everywhere
except the mixed markup tier, where a hostile block sits in the middle of a form
whose extra controls belong to that block: they render in the middle and the key
lists them last. Every such form is on the mixed tier and nowhere else, which is
asserted rather than assumed. The selectors are the contract; the order of the
list is not.

### What surprised me

How much of the extractor turned out to be policy rather than mechanism. The DOM
walk itself is a few dozen lines and was right almost immediately. What took the
time was deciding what a honeypot is, which label source wins, when a canvas
counts, whether two adjacent selects are an expiry pair, and what "cannot be
accessed" means for a frame. Every one of those is a judgement that shows up in
a report somebody reads, and none of them are discoverable from the DOM API.

The corollary is that the tests worth having are the ones that pin the
judgements, not the ones that pin the traversal. The traversal has a handful of
tests; the honeypot rule, the group detector, and the selector order have
dozens.

## 2026-08-26: P3, the rule baseline, the audit engine, and the CLI

The phase that turns a corpus and an extractor into something worth installing.
No machine learning in it, which is the whole point of the build order.

### What was built

`classify/rules_table.py` is the substance. It is a table of pattern, label,
weight, and signal name, grouped by label, with a locale tag on every row whose
wording belongs to one language. `classify/rules.py` owns the six-tier precedence
of spec section 10.1 and owns no vocabulary at all, so adding a language never
touches control flow and changing precedence never touches a word list. Around
those: the finding catalogue with its fix templates as data, the ordered decision
procedure, three renderers, the command surface, and the config file.

### The design decision the phase turned on

**Ties are the safety mechanism, not a shortcoming.**

The specification says a tier decides when it yields a unique match and otherwise
falls through, and that a tie surviving every tier is `UNKNOWN`. It reads like a
tidy-up clause. It is the single most load-bearing sentence in section 10.1.

German writes `Straße und Hausnummer` for both a whole street address and the
first of several address lines. French writes `Adresse` for both. A field
labelled only "Password" is a login field on one page and a registration field on
the next. In each of those the wording genuinely does not distinguish two labels,
and the correct answer is that the tool does not know.

The moment that clicked, the table changed shape. Instead of writing a pattern
per label and hoping they did not overlap, the overlaps became deliberate: both
labels carry the same phrase at the same weight, the tier ties by construction,
and the engine falls through to something that might separate them. The
false-positive property fell out of that rather than being tuned into existence.
It passed the first time it was run, across the whole correct-markup slice, with
no findings at any severity at all.

The alternative would have been to break each tie by picking a favourite. That
produces a confident instruction to write the wrong token into somebody's
production markup, which is precisely what law 1 exists to prevent, and it would
have looked like better coverage on every metric except the one that matters.

### Three places the specification had to be read rather than transcribed

Written down here because a reader of the code should not have to reconstruct
them, and because each is a place where two sections of the specification pull
against each other.

**`COMPOSITE_FIELD` has no branch in the pseudocode.** Section 11.1 gives its
trigger as "inferred `COMPOSITE_UNSPLIT`", which taken literally fires a warning
on every correctly declared MM/YY input; section 8.4 makes any finding above
`INFO` on a correct form a defect. Both hold only if the finding is about the
*absence* of the declaration, so it sits where `MISSING_AUTOCOMPLETE` sits and
carries the composite's own fix.

**`AUTOCOMPLETE_OFF` has no stop marker.** The pseudocode writes "; stop primary"
on two branches and not on this one, but `autocomplete="off"` parses to a null
token, so without the stop a field collects both `AUTOCOMPLETE_OFF` and
`MISSING_AUTOCOMPLETE`: two primary findings with two contradictory fixes. The
prose above the pseudocode says first match wins, so it stops.

**The cross-origin frame fix text contradicts section 9.6.** Section 11.1's
template ends "expose it in light DOM or declare autocomplete on the host", which
is sound for a closed shadow root and nonsense for a frame the page does not own.
Section 9.6 requires the text to say a hosted payment field is common and
correct. The more specific section wins and the override is data beside the
template rather than a branch in a renderer.

### What went wrong

**Two browsers, one thread.** Adding a session-scoped browser fixture for the
audit suite made the extractor suite fail with "It looks like you are using
Playwright Sync API inside the asyncio loop. Please use the Async API instead."
Nothing was using the async API. Playwright's synchronous wrapper drives a
greenlet on one event loop per thread, and a second live session finds that loop
already running. The message names a symptom that has nothing to do with the
cause, and it cost about twenty minutes of looking in the wrong place.

There is now one browser fixture in the root `conftest.py`, shared by every
suite. The same constraint is why the end-to-end CLI tests run the tool in a
subprocess: the CLI opens a browser of its own and cannot do that while the test
session's browser is alive. That turned out to be an improvement rather than a
workaround, because a subprocess exercises the real exit codes as a shell sees
them.

**The pre-commit whitespace hook ate the golden snapshots.** `rich` pads a table
row out to the full terminal width, `trailing-whitespace` trims it, and the first
commit of the snapshots rewrote every one of them and left the suite failing
against its own repository. The hook now skips `tests/golden/`, which is a narrow
exemption for the one directory whose whole purpose is to be byte-exact.

**A German placeholder read as a name field.** On the hostile tier the label is
stripped and the placeholder is all that survives. The German email placeholder
is `name@example.com`; the at sign does not survive normalisation, so the token
stream is `name example com`, and the whole-name rule fired on it. The fix is a
rule matching the reserved documentation domain of RFC 2606, which is what
essentially every placeholder on the web uses, and it turned ten wrong criticals
into ten right ones across the whole hostile slice rather than only fixing the
German case.

**A Japanese section heading read as a card verification code.** The rule for the
Japanese security code matched the bare word for "security", which is what a
form's own security section is headed with, so a login password field picked it
up from the context tier. Narrowed to the full compound. Both of these were found
by sweeping the generated corpus and cross-checking every declaration finding
against the generator's own provenance, which is a check worth keeping.

### The Japanese postal mark, and an honest dead rule

Section 10.1 names the postal mark among the words `postal-code` must match. It
cannot fire. The normalisation of section 9.7 treats a lone symbol character as a
delimiter, so the mark never reaches a token stream, and the Japanese postal
field is reached through its word form instead.

The rule is in the table anyway, with a comment saying it cannot fire and why,
and a test asserting both halves of that. Making it reachable means changing what
counts as a token character, which changes every golden snapshot and every
committed fixture expectation, and that is a deliberate decision with a cost
rather than a quiet fix. It is written up in the notes for P4.

### The thresholds are a mapping, and the file says so

Section 11.3 has the two thresholds derived on the dev split at P4 against a
precision target committed before the measurement. Until then the rule engine's
tiers map to the same two bands. The mapping puts `HIGH` and `MEDIUM` in the
confident band and `LOW` in the near-miss band, and the reasoning is in the
committed file: `MEDIUM` is what an identifier, a placeholder, or an option list
earns, and those are the only evidence a hostile page leaves standing. Putting
them in the near-miss band would mean the tool could never say anything above a
note about exactly the pages it exists for.

Every key in that file that would hold a measurement is null, and the reports say
in words that the thresholds behind their confidences are a mapping rather than a
measurement. A plausible number sitting in a file the runtime reads would be a
law 3 violation with a straight face.

### What surprised me

How much of the phase was deciding what *not* to report. The finding catalogue
took an afternoon; the equivalence sets, the asymmetry that makes a declaration
authoritative unless the tool is confident it is wrong, the tiers that fall
through rather than guess, and the labels the table deliberately cannot separate
took the rest of it. Every one of those makes the tool quieter, and every one of
them is the difference between a check somebody keeps and a check somebody
deletes.

## 2026-08-26: P4, the prediction goes in first

Phase P4 opens with a commit that contains no code.
`experiments/predictions/p4-threshold-derivation.md` states, before the model
exists, how the two decision thresholds will be computed, what precision target
drives them, which classes get which calibration method, what the feature caps
are, and what the confusion matrix is expected to show.

The fourth law is the reason. A prediction committed after the measurement is not
a prediction, and the ancestry check at P5 will verify that this commit is an
ancestor of the commit carrying the derived values.

Writing it first also settled a real ambiguity for free. The task file asks for
the low threshold as the smallest confidence at which the near-miss band still
captures at least half of what the high threshold gives up. Captured recall only
ever falls as that threshold rises, so every value below a qualifying one also
qualifies, the smallest qualifying value is always zero, and a threshold of zero
says nothing. The prediction file records the non-degenerate reading, which is
the greatest qualifying value, and it records it at a point where there were not
yet two candidate answers to choose between.

## 2026-08-26: P4, the n-gram model, its calibration, and its ONNX export

### The ONNX route was a design decision, not a retreat

Section 10.5 anticipates a fight with skl2onnx's text vectorizer converters and
names a fallback: move the whole text pipeline into hand-rolled Python, export
only the linear layer, and take that quickly rather than spending a day coaxing a
converter.

The fight never started, because the feature set was never convertible. Section
10.2 has five feature blocks and three of them are categorical one-hots,
option-shape booleans, and structural buckets, which no scikit-learn transformer
produces. Putting the whole featurisation in the graph would have meant writing
custom converters for three bespoke transformers **and** trusting the vectorizer
converters, which is a larger version of exactly the risk the section warns
about. The fallback's Python featuriser is not a retreat from the design; it is
the only design in which one implementation serves both paths, which section 10.2
required from the beginning.

The second argument arrived for free and is the one that will matter longer. A
vectorizer anywhere in the inference path puts scikit-learn on the dependency
list of a tool that installs with `pipx`. The route taken means an installed
wheel needs numpy and onnxruntime and nothing else.

The cost is real and is recorded rather than waved past: a Python analyser is
slower than a C one, and its faithfulness to `char_wb` is a claim rather than an
identity. So it is tested. `tests/unit/test_features.py` asserts, over ten inputs
including empty strings, words shorter than the n-gram length, and Japanese text,
that this project's enumeration is character for character scikit-learn's. The
short-word rule is the detail an independent reimplementation gets wrong: a word
shorter than n yields its padded self once rather than once per n, and getting
that wrong would silently triple the weight of every two letter token.

### The opset probe, and why the warning is recorded rather than suppressed

Section 10.5 says to export at the newest opset the resolved onnxruntime accepts,
determined by probe. The probe walks down from the newest the installed `onnx`
package defines and takes the first that both converts and opens in a session.

```
probe rejected opset 27: onnxruntime supports ai.onnx to opset 26; 27 is under
                         development
probe accepted opset 26
```

skl2onnx warns at both attempts that the requested opset is above the newest it
has been tested against. That warning is in ADR 0006 rather than filtered out,
because it is precisely the case where a successful export proves nothing. What
proves something is the parity gate, and that is the point of section 10.5 having
a gate rather than a deliverable.

### The graph turned out to hold its weights in an attribute

Worth writing down because it changed a design. The exported graph is one
`ai.onnx.ml.LinearClassifier` node followed by an L1 `Normalizer`, and the
coefficients, the intercepts, and the class order live in the node's
**attributes**, not in graph initialisers. onnxruntime does not hand a caller a
node's attributes, so the inference path cannot read its own weights, and naming
the n-grams behind a prediction would otherwise have required the `onnx` package
at runtime to produce one line of a report.

Hence `models/evidence.json`: each class's highest weighted features, written by
the same training run. A derived file is a drift risk, so the parity suite reads
the weights back out of the graph and asserts the table agrees with them. A stale
evidence file now fails the build rather than naming the wrong n-grams in a
finding, which would have satisfied law 1 in form and violated it in substance.

### The training run

Every number here is in `models/dev_metrics.json` and
`models/train_manifest.json`, which is where they came from.

```
results: models/dev_metrics.json
train   300 forms   2889 rows
dev     120 forms   1118 rows
features 6656 columns: char 4905, word 1701, categorical 32, option 5, structural 13
sweep    C in {0.25, 0.5, 1.0, 2.0, 4.0, 8.0}, chosen 8.0 on dev macro-F1
dev macro-F1  0.5813    dev accuracy 0.7093
```

**The sweep chose the edge of its own grid.** The grid was pre-registered, so it
is not being widened now: widening a pre-registered grid because the answer landed
at its edge is how a sweep becomes a search for a number. The consequence is
recorded in the model card instead, and it is that this model may be less
regularised than a wider grid would have chosen. A later phase that revisits it
re-registers first.

### The predictions, and which of them survived

The prediction file was committed before any of this existed. Four of its claims
were checkable today.

**Held.** Most classes would fall below the isotonic switchover. In fact *every*
class did: no label reached one hundred dev positives, so every calibrated class
in this model is calibrated by Platt scaling and twelve classes with no dev
positives at all are uncalibrated and named as such in the card.

**Held.** The held-out locale would be materially worse. `fr-FR` is the worst
cell in the per-locale table by a wide margin, and it is the only locale the model
never trained on.

**Held.** The hostile tier would be the weakest. It is, by a similar margin.

**Held, mostly.** Three of the four confusion pairs section 13.2 names are in the
confusion table: telephone against national telephone in both directions, the
address levels against country, and the address family against itself.

**Contradicted.** `username` against `email` is not in the table, and the
prediction that the derived high threshold would sit *below* the rule engine's
confident band is wrong in the other direction: it sits well above it. Both are
worth more than the three that held. The first is contradicted by the split
rather than by the model, since `username` has no dev rows at all here and `email`
is the one label the model gets exactly right. The second is the finding of the
phase and has a section of its own below.

### The threshold derivation, and a tool that got much quieter

The pre-registered optimisation was applied without amendment.

```
results: src/autofill_audit/audit/thresholds.json
target precision   0.98
tau_high           0.9498622881050033
tau_low            0.8237827291133224
dev precision      1.0 over 15 accusations
dev recall         0.0372 of 403 fields that need one
recall at any confidence  0.6253
near-miss band captures   0.2953, which is 0.5021 of the recall given up
```

Two things about that need saying plainly rather than being left in a file.

**The precision target is met on a denominator of fifteen.** A precision of one
over fifteen accusations and a precision of one over fifteen hundred are the same
number and are not the same claim. The derived block therefore records the
denominators beside the rates, so that a reader of the file does not have to go
and find out which it is, and the model card says the same thing in words.

**At this threshold the model is a much quieter tool than the rule baseline.** On
the dev split it would raise fifteen missing-declaration findings where four
hundred and three fields need one. That is what a pre-registered high precision
target buys on a model whose calibrated confidences are honest about how often it
is right, and it is the correct outcome of the policy rather than a failure of it:
section 11.3 says to fix the target high because a false critical costs far more
than a missed one, and this is what "far more" looks like when it is taken
literally.

It is also the reason the comparison the README is not yet allowed to make is
going to be interesting. The rule engine accuses on far more fields at a
confidence that is not a probability at all. Which of those a developer prefers
is a real question, it is exactly what P5's finding-level precision and recall
measure, and neither engine's number exists yet.

### One threshold document, two engines

The derived boundary sits at roughly nought point nine five. The rule engine's
confident band starts at nought point seven, and its `MEDIUM` tier *is* nought
point seven. A single pair of thresholds across both engines would therefore have
moved every rule-engine finding on every page, churned every golden snapshot, and
done it as a side effect of training a model.

So `thresholds.json` grew a block per engine at schema version two, `load_thresholds`
takes the engine name, and the CLI resolves the engine first and then asks for
that engine's block. The rule block is byte-identical to what P3 committed, and
the golden diff after the whole phase is the version string and nothing else,
which is the evidence that it worked.

An engine with no block is an error rather than an inheritance. That will bite P6
when the language model engine arrives with no threshold block, and it is meant
to: an engine's decision boundary is a recorded choice, and inheriting another
engine's would apply one confidence scale to numbers produced on a different one.

### The abstention branch, made explicit

P3's handoff pointed out that a model emitting `UNKNOWN` with a high calibrated
probability would reach the right outcome by accident, through `declaration_for`
returning nothing rather than through the confidence, and said it would be worth
an explicit branch. It is now one: when the winning class is `UNKNOWN` the
reported confidence is zero, exactly as the rule engine reports it, and the
calibrated probability of the runner-up stays on `runner_up` where the confusion
analysis at P5 can still read it.

### Latency, informally

Not a measurement of record. P5 measures latency properly, with percentiles, a
warmed session, and a run manifest. This is a sanity check that the numbers are
in the range section 5.3 states as a target:

```
informal, forty dev pages, warmed session, threads pinned
ngram   per field p50 164 us,  p95 218 us
rules   per field p50  37 us,  p95  73 us
```

Both are comfortably inside the sub-millisecond per-field target, and the
difference between them is dominated by the Python n-gram enumeration rather than
by the session, which is the cost ADR 0006 said the route would have.

### What surprised me

**How much of the phase was arranging for the numbers to be checkable rather than
producing them.** The model took an afternoon. The prediction file, the per-engine
threshold document, the evidence table and the test that keeps it honest, the
denominators beside the rates, and the dirty-tree flag on the training manifest
took the rest of it, and every one of them exists so that a number in this
repository can be argued with.

**The dirty-tree flag caught its first real case immediately.** Section 18 says a
result produced from a dirty tree is marked dirty and is not citable. The first
full training run was made from a working tree with uncommitted changes and the
manifest said so, so the run was thrown away and repeated from a clean tree. The
flag also needed one fix to be honest: the output directory is untracked on a
first run, so counting it would have marked every first training run dirty by
construction and made the flag mean nothing. It now excludes the output directory
and only that.

---

## 2026-08-26: P5, evaluation and the Triage integration

### What was built

The metrics module of spec section 13.2, the JSONL run-log writer at the schema
of section 13.1 with its sibling manifest at section 18, `autofill-audit eval`,
the bridge to the external evaluation harness, the prediction-ancestry check that
makes law 4 mechanical, and the first result files this repository has ever
carried: two development sanity runs, two test-split runs, and one significance
analysis over the pair.

The README carries numbers for the first time, and every one of them is a link
that a CI job follows to a result file, to that file's manifest, and to a commit.

### The result, which is not the one the ladder was built expecting

On the test split the rule baseline beats the n-gram model on macro-F1 in every
slice measured, by margins between one tenth and one third of a point. The model
does not win anywhere. Not on the hostile tier, where a learned model's
redundancy was supposed to pay; not on the unseen locale, where character n-grams
were supposed to degrade more gracefully than a vocabulary of regular
expressions.

Three of the seven pre-registered predictions were about the model winning and
all three failed. A fourth, about which confusion pairs would appear, failed
completely: not one of the four pairs spec section 13.2 names occurred even once,
in either direction, for either engine. The three that held were about the
*shape* of the system rather than about the model. Both engines stay inside a
millisecond per field, page load dominates the wall time so completely that
classifier latency is a rounding error, and the model does abstain less often
than the rule table.

The full accounting sits in `experiments/predictions/p5-statistical-policy.md`
beside the predictions themselves.

**Why this is a P5 result rather than a P4 defect.** P4 measured the model on the
development split and reported what it saw, honestly, and never measured the rule
baseline on the same rows, because P4 had no evaluation runner. Nobody had put
the two engines side by side until this phase, which is what an evaluation phase
is for. The development-split sanity runs, taken and committed before the
pre-registered policy file and cited inside it, already showed the same ordering,
so the test split confirmed rather than revealed it.

**Why the model loses is worth stating plainly**, because the number that
explains it is already in the artefacts. The rule table answers `UNKNOWN` on a
quarter of the fields and is right on almost everything it does answer; the model
answers almost everything and is right on about seven tenths of that. Macro-F1
over the union of observed labels punishes exactly that: a model that guesses a
rare class and is wrong pays twice, once in that class's recall and once in the
recall of the class it should have chosen. Abstention is not the model being
timid. On this corpus it is the better policy, and the rule table has it by
construction, because its default branch is a tier that never clears a threshold.

### The finding nobody had noticed: this corpus cannot certify anything

The larger result of the phase is statistical rather than about either engine.

Spec section 13.3 requires resampling at the template level, because fields
inside a template share an author. P1's leakage rule assigns whole templates to
partitions, one template per family to test, so the test split holds five
templates. A paired sign-flip permutation over five clusters has thirty-two
arrangements, so the smallest two sided p value the design can produce is 0.0625.

The pre-registered false discovery level is 0.05. **The design cannot reach it.**
No comparison clustered by template on this split can ever be significant, at any
effect size, and eleven of eleven comparisons in the analysis are reported as
inconclusive for that reason. Seven of them sit exactly at the floor, meaning the
observed difference was more extreme than all thirty-one other arrangements the
design permits, which is the strongest evidence available here and is still not
significance.

This was computed and written into the policy file before the test runs, from
`corpus/split.json` alone, which involved no test-split measurement. Writing it
afterwards would have been indistinguishable from an excuse.

The honest report of it is "inconclusive: the design cannot reach alpha", never
"no significant difference". Those two sentences describe different worlds and
only the first is true here. A secondary analysis clustered by form reaches
significance easily, and it is labelled anticonservative everywhere it appears,
because clustering by form asserts that two locales of one template are
independent, which is a stronger claim than section 13.3 makes. Nothing in the
README cites it.

The fix is more templates per family, which changes the corpus and therefore the
model, so it is P6 work rather than a footnote here. It is in the notes for P6
with the arithmetic.

### The harness, which is the phase's actual deliverable

The split runs cleanly through the middle of that package. Its statistical
primitives fit this project exactly and were used unchanged; its data model, its
ingestion layer and its comparison entry points did not fit at all.

`permutation_p_value` fit because it takes the null distribution as an argument,
which is the seam a caller with its own resampling scheme needs.
`benjamini_hochberg` fit unchanged and needed nothing. Its verdict vocabulary
turned out to contain the three categories section 13.3 demands plus a fourth for
a design that cannot reach alpha, which is the category every comparison here
lands in.

Everything shaped like a training run did not fit. `JsonlParser` claims a run log
and then refuses it for having no step field, and there is no step to add,
because the file has no time axis. No public entry point accepts a cluster
assignment. Neither comparison mode is paired. Both reduce a metric series to a
final window mean, which a categorical per-field outcome does not have.

Five issues are filed on that repository, each with a concrete API proposal, and
`docs/cross-repo-tasks.md` carries the ledger. Two workarounds live here in the
meantime, both labelled in every result file they produce: the clustered null is
built in `evaluate/triage_bridge.py` and handed to the harness's p value
estimator, and the practical-effect gate is applied here because the harness's is
relative where this project pre-registered an absolute one.

That second gap changed no verdict on this data, because the underpowered gate
fires first everywhere, and it is filed anyway. A gap that happens not to bite on
one dataset is still a gap, and the dataset it would bite on is any slice with a
small baseline, which is most of what P6 adds.

**The anticipated task was aimed one layer too low.** The ledger predicted, before
P5 began, that categorical-outcome support in the permutation machinery would be
the friction. It was not needed at all. `permutation_p_value` never sees an
outcome, only an effect and a null, both floats. The categorical part of the
problem lives entirely in the statistic and the statistic is the caller's. What
actually broke was one layer above, in the data model.

### The bug that would not have raised

`classify` ends with `return rank(findings)`, so it returns severity order rather
than input order, and `Finding.tag` is not a unique key when one metric is
compared across seven slices, which is exactly this project's family. The first
cross-check run attached the verdict for `macro_f1/all` to a row labelled
`finding_recall`, and every value in the row was plausible. Nothing raised. It
was caught by reading one line of output that should have said `macro_f1` and did
not.

The bridge now rejoins on the identity of the result object each finding carries.
That is not a contract worth depending on, so it is filed as its own issue with
two proposed fixes.

### Deviations, and decisions the specification left open

**The run log's `engine` field carries the engine's own name.** Spec section 13.1
writes `ngram-onnx` and section 13.4 uses the same label in its table, and
`Prediction.engine` says `ngram`. Carrying two names for one engine across a
repository is how a comparison table becomes ambiguous, so the run log records
what the engine calls itself and a report can label its column however it likes.

**`confidence_kind` is mapped rather than copied.** Section 13.1's vocabulary is
`calibrated`, `rule_tier`, `self_reported`; the engines say
`calibrated-probability` and `tier`, because those are the words P3 and P4 made
load bearing in the renderers. The mapping is written down once, in
`evaluate/runlog.py`, and it is total: an engine whose word is not in it raises
rather than defaulting. P6 adds its word there deliberately.

**The reporting minimum now applies to the finding-level rates.** P4 applied it to
grid cells only and asked P5 to decide the rest. It is decided, in the policy
file, before the test runs: each rate is judged against its own denominator. It
fires immediately, on `WRONG_AUTOCOMPLETE` for both engines, where eleven fields
were eligible. The counts are still reported and the rates are withheld.

**It does not fire on the locale by tier grid**, which is where P4 predicted it
would. That grid has twenty-four cells over a thousand-odd fields, so every cell
clears thirty comfortably. The rule is exercised against real committed data by
the finding-level case instead, and by a unit test that builds a thin cell
directly.

**`findings.jsonl` is a fourth artefact per run**, not in the specification's file
list. Whether a page *needed* an accusation depends on the difference between
declaring nothing, declaring off, and declaring a token outside the
specification, and section 13.1's row carries only `declared_token`, which is
null in all three. Without the file the finding-level significance test could not
be reproduced from committed artefacts, and a number nobody can recompute is a
number law 3 will not allow into the README.

**Results are filed under `experiments/results/<split>/`.** Not tidiness. The
pre-registered policy predicts about `experiments/results/test/`, and the
development runs precede that policy and make no claim it covers. One flat
directory would have made law 4's own check fail on a run that was correctly
taken before the prediction was written.

**The harness is a development dependency, not a runtime one.** Installing it
pulls thirteen transitive packages including tensorboard, grpcio, pandas, plotly,
pillow and werkzeug, and the audit path never imports it. A `pipx install` that
dragged a training-metrics logging stack onto a developer's machine so that a
command they will never run could compute a permutation p value would be the
wrong trade. The consequence, stated here so it is not discovered later, is that
the shipped wheel cannot compute its own significance tests. The narrower extra
that would fix it is proposed in the ledger.

**The descriptor cache is now bound to a corpus.** P4 left it keyed on the form id
and nothing else, as a documented sharp edge. A stale cache is survivable for a
training run and is a wrong headline number for an evaluation, so `bind_cache`
records the corpus manifest sha and refuses a mismatch rather than either reusing
it or silently emptying it. Both test-split runs bypassed the cache entirely and
extracted through a real browser, so their load and extract columns are
measurements on both engines rather than a cache read on the second.

### What surprised me

**The version string in the committed run logs says 0.2.0.** The test runs were
taken before the version bump, so `engine_describe.tool_version` records the
version that was actually running, and the manifest's commit resolves to a tree
where `__version__` is that string. It is consistent, and it looks wrong at a
glance. Re-running to make it prettier is exactly the regeneration section 18
forbids, so it stays, and this paragraph is the explanation.

**Every prediction that failed was about the model and every prediction that held
was about the system.** That is worth carrying into P6, where the temptation to
predict that a twelve-billion-parameter model will win will be considerable. The
predictions that held were the ones where the mechanism was already understood:
page load dominates because a browser is slow, the model is slower per field
because it enumerates n-grams in Python. The ones that failed were the ones where
a mechanism was assumed rather than measured.

**The finding-level precision is exactly one for both engines.** Two hundred and
six accusations from the rule table, thirty-two from the model, and not one of
them wrong on the test split. That is the threshold policy working as designed on
both engines, and it means the interesting axis between them is recall alone.

### The gate that only failed once it was real

The traceability job went red on the first push of this phase, on a check that
had passed locally minutes earlier, and the failure was correct.

`--resolve` asks this repository to produce the commit object each manifest
names. The job checked out at the default depth of one, so the clone held only
the tip commit, and every citation of a run taken in an earlier commit failed
with a message saying the commit does not resolve in this repository. That
sentence was true of the clone and false of the repository.

Reproduced locally with `git clone --depth 1` before changing anything, because a
CI failure that is fixed without being reproduced is a CI failure that is guessed
at. The fix is `fetch-depth: 0` on that job, the same setting the ancestry job
already carried for the same reason: both checks ask questions about history, and
history is the input.

Worth recording for two reasons. It is the first time a gate in this project has
gone red on a real defect rather than on a deliberately broken scratch branch, so
the P0 proof-of-failure argument now has a natural example beside its manufactured
ones. And it is a defect that could only appear once law 3's chain went from a
pattern match to a resolution: the check that had run in CI since P0 would have
passed on this commit forever, because it never asked git for anything.

## 2026-08-26: P5R, the corpus power repair, written before anything moved

This entry is committed **before** the work it describes, together with
`experiments/predictions/p5r-power-repair.md` and the changelog entry. Ground
rule 4 forbids baseline drift, and from P5 onward this repository carries
recorded results, so a phase that is about to move every recorded metric in it
owes the explanation first rather than afterwards. Writing it afterwards would be
indistinguishable from an excuse, which is the same argument P5 made for
computing its own power before its runs.

### What is wrong, and why it is not fixable by measuring harder

P5 found that the test split cannot certify anything. Spec section 13.3 requires
the resampling unit to be the template, P1's leakage rule assigns whole templates
to partitions, and the realised grid carried five templates per family at a
three, one, one split. The test partition therefore held five templates, a paired
sign-flip permutation over five clusters has thirty-two arrangements, and the
smallest two sided p value such a design can produce is two over thirty-two.

```
test templates   arrangements   smallest attainable two sided p
      5                32                    0.0625
      6                64                    0.0313
      8               256                    0.0078
     10              1024                    0.0020
```

The pre-registered level is the one P5 fixed before its runs, and thirty-two
arrangements cannot reach it. All eleven of P5's comparisons came back
inconclusive because the design cannot reach alpha, seven of them sitting exactly
at the floor. More resamples do not help: at five clusters the test is already
exhaustive. Only more templates help.

### The repair, and the three options it was chosen from

The notes for P6 set out three ways forward: generate more templates per family,
accept the floor and report every comparison as inconclusive, or pre-register a
different alpha. The third would clear the floor at a level of one in ten and
looks exactly like moving the goalposts, because it would be chosen after seeing
that the original level was unreachable. The second leaves the headline benchmark
of spec section 13.4 answering its question with effect sizes and no significance
at all.

The first was chosen, and it is being done now rather than at P6 so that the
language model arrives at a corpus that can certify a difference. The cost is a
regeneration, a retraining, a threshold rederivation and a re-measurement, all
four of which are scripted and three of which have been done once already.

### Why every recorded number in this repository is about to move

Eight templates per family instead of five, split five, one, two instead of
three, one, one. That is the whole change and everything below follows from it
mechanically:

- the realised grid changes, so the corpus manifest sha changes;
- the descriptor cache is bound to that sha, so it is refused and rebuilt;
- the training partition grows from fifteen templates to twenty-five, so the
  model, its vocabulary, its calibration and its evidence table are all
  different, and none of them is comparable to P4's;
- the dev partition is a different five templates, so both decision thresholds
  are derived on different data and may land anywhere;
- every metric in the model card and in `models/dev_metrics.json` moves;
- the test partition is ten different templates, so both engines' test-split
  numbers move, in either direction, and a movement in the rule baseline is not
  a change in the rule table but a change in what it was asked about.

None of that is a regression and none of it is a defect. It is one deliberate
change to the corpus design, and the reason it is written down in advance is that
a reader comparing the README against its own history a month from now will
otherwise see every number change at once with no stated cause.

### What deliberately does not move

The seed stays where P1 set it. The held-out locale stays `fr-FR`, which spec
section 8.6 forbids changing and which nothing here touches. The excluded
partition keeps the rule P1 gave it. The statistical policy is untouched: the
alpha, the false discovery rate, the absolute practical-effect threshold, the
clustering unit, and the target precision behind tau_high are all exactly what P4
and P5 pre-registered. Repairing the corpus is only honest if the standards it is
measured against stay where they were, and a phase that moved a threshold and a
corpus at the same time would have produced two changes and no attribution.

### The one addition, and the arithmetic behind its constant

A new clause joins law 2's enforcement: every label a model can predict must
appear in the train partition with at least twenty rows. Three labels currently
sit at zero there, `country-name`, `one-time-code` and `street-address`, which
means the model has been asked about labels it has never once seen, and every one
of those is a class it can only get wrong.

Twenty is arithmetic rather than taste. A template is generated in six locales
and four tiers at one variant, and the held-out locale is lifted out of train, so
one training template contributes exactly twenty training rows for a field it
carries in every locale. The constant therefore says "at least one whole training
template carries this label", which is the smallest statement about a label that
is not an accident of one locale profile. The three new templates per family are
designed to carry the starved labels deliberately rather than to acquire them by
luck.

### The order of the commits, which is the part that matters

This entry, the changelog entry and the prediction file are one commit and they
are the first commit of the phase. Then the templates, the regeneration and the
retraining, with the new model artefacts and the new model card in a single
commit, as the model-card ground rule requires. Then the new runs and the new
analysis. The old
result files are never touched: spec section 18 makes them append-only history,
they were correctly taken, and the honest description of them is the first,
underpowered measurement rather than something to be tidied away.

## 2026-08-26: P5R, what the repaired corpus measured

The entry above was written before the work. This one is written after it, and
the two are deliberately separate commits so that a reader can see which claims
predated the data.

### The design has power now, and the first thing to say is what that changed

```
results: experiments/results/analysis/2026-08-26T06-23-41Z_p5r-analysis_0d900ff/analysis.json
                          old design      new design
test templates                     5              10
sign-flip arrangements            32            1024
smallest attainable p         0.0625          0.0020
comparisons in the family         11              11
inconclusive: cannot reach alpha  11               0
```

Eleven of eleven unreachable became zero of eleven unreachable. Every comparison
now lands in one of the three categories spec section 13.3 requires, which is
what the phase was for.

**All eleven land in the same one: no significant change.** Five of them have an
uncorrected p value below the level and none survives the Benjamini Hochberg
correction across a family of eleven. That is not the same finding as the last
one and the difference matters: last time the design could not answer, this time
it answered and the answer is that ten clusters do not resolve these effects.

The temptation to report the uncorrected column, or to correct inside a subset,
is exactly what the family size in the result file exists to make visible. The
family is eleven because eleven comparisons were run, not because eleven were
worth reporting afterwards.

### The engines, old design beside new

Both columns are macro-F1 on the test split. The old numbers are from the first,
underpowered measurement and are not comparable as measurements of the same
thing, because the test split is now ten different templates. They are here
because ground rule 4 requires a moved metric to be explained, not because the
two are being averaged.

```
results: experiments/results/test/2026-08-26T06-18-34Z_p5r-rules_0d900ff/metrics.json
                              rules old   rules new   ngram old   ngram new
macro-F1                         0.7785      0.7911      0.4151      0.7394
micro-F1                         0.7744      0.7678      0.7041      0.8226
macro-F1 unseen locale           0.7193      0.7276      0.4057      0.5637
macro-F1 clean tier              0.8500      0.8677      0.5885      0.9350
macro-F1 hostile tier            0.5163      0.4681      0.4052      0.5409
abstention rate                  0.2676      0.2620      0.0508      0.0363
accuracy when committed          0.9773      0.9702      0.6996      0.8204
```

**The rule baseline barely moved and the model moved by a third of a point of
macro-F1.** That is the shape the prediction file expected: the rule table is a
fixed function of the markup and a different set of templates asks it slightly
different questions, while the model gained ten training templates and lost its
three untrainable classes.

**The registered predictions, and which held.**

- *The ordering persists.* Held on macro-F1, overall and on the unseen locale.
  The rule baseline still leads the label-weighted average.
- *The model improves absolutely.* Held, and by more than expected.
- *The comparisons clear the design floor.* Held. Zero comparisons report the
  underpowered verdict.
- *Page load still dominates.* Held. The load and extract share is above
  ninety-eight percent for both engines.
- *Latency stays inside a millisecond and the model stays slower.* Held on both
  halves.
- *Finding-level precision stays at or very near one.* Held for the rule
  baseline exactly and held loosely for the model, which is discussed below.

### The two averages disagree, which is the result worth carrying forward

Macro-F1 says the rule table wins. Micro-F1 says the model wins. Both are in the
same two files and both are correct.

The mechanism is the abstention asymmetry, seen from the other side this time.
The rule table answers `UNKNOWN` on about a quarter of the fields, which costs it
nothing under macro averaging (an abstention is a miss on one class) and costs it
a quarter of the field-weighted denominator. The model answers nearly everything,
which earns field-weighted accuracy and pays label-weighted average whenever it
guesses a rare class wrongly.

At P5 the model was bad enough that both averages agreed. It is not any more, and
the honest report of a two-engine comparison on this corpus now has to carry both
columns and say what each of them weights. P6's headline table has three engines
and the same problem, one column wider.

### The model's first wrong accusation

The rule baseline accused four hundred and forty-nine fields and was right about
all of them
([metrics.json](experiments/results/test/2026-08-26T06-18-34Z_p5r-rules_0d900ff/metrics.json)).
The model accused three hundred and thirty-four and was wrong about nine
([metrics.json](experiments/results/test/2026-08-26T06-21-03Z_p5r-ngram_0d900ff/metrics.json)).

That is the first time in this project that either engine has told a developer to
add a token the answer key disagrees with, and it deserves to be recorded rather
than rounded. The threshold policy did not change: the target precision behind
`tau_high` is the pre-registered one and the derivation script was run
unmodified. What changed is that the derived threshold sits on a model whose dev
precision at that point was itself below one, so a test-split precision below one
is the design working rather than failing. A precision target is a target, not a
guarantee, and a project that reported the target as though it were the outcome
would be reporting a policy as a measurement.

### Calibration got worse, and the calibrator stayed

Expected calibration error before calibration was lower than after it. The
uncalibrated model of this corpus is already close to honest, and refitting
forty-two one-vs-rest sigmoids on a dev split of one template per family and then
renormalising moves classes that were already well behaved.

The calibrator stays, for two reasons that are in the model card in full: macro-F1
is higher with it, and the argument in spec section 10.4 is about the number a
finding quotes rather than about an average gap. What changes is the card, which
now says the error went the wrong way and by how much. Dropping the calibrator
because its summary statistic got worse, without re-registering, would be tuning
on the thing being measured.

### What did not go as expected

**One class reached the isotonic switchover.** `NOT_AUTOFILLABLE`, the label that
covers every search box and consent checkbox, is the first class in this project
ever to have enough dev positives for isotonic regression. P4 predicted none ever
would and that prediction was correct for its corpus.

**The confusion table is smaller and more structural.** The largest single
confusion on dev fell from the forties into single figures. What is left is
mostly genuine ambiguity: a telephone against a national telephone, an
organization against a nickname, a country name against a country.

**The mixed tier is the model's weak tier now.** It leads the rule baseline on
clean, partial and hostile markup and trails it on mixed, which is the tier built
to look like a real page whose sections were written by different teams at
different times. A model that is better on each tier separately and worse on the
tier that mixes them is worth a paragraph in the report rather than a footnote.

### The version string in the committed run logs says 0.3.0

Again, and for the same reason as at P5: the runs were taken before the version
bump, `engine_describe.tool_version` records what was actually running, and the
manifest's commit resolves to a tree where that is true. Re-running to make it
prettier is the regeneration spec section 18 forbids.

## 2026-08-26: P6, the predictions and the threshold decision, before any of it runs

The prediction file went in first, as the first commit on the branch, before the
client existed. Two things in it were decided in advance because both would have
been contaminated by seeing the numbers.

**The comparison family.** P5R corrected across eleven comparisons for one engine
pair. A three-engine benchmark has three pairs, and the family could reasonably
have been thirty-three, or twenty-two, or eleven with the language model
substituted in. The temptation is specific and foreseeable: the comparison this
phase exists to make is the one against the language model, and a family
containing only that pair would be a third the size and would produce smaller
adjusted p values for exactly the comparisons the project most wants to be able
to report. So the size was fixed at thirty-three while fixing it was still
costless, along with the consequence that every rules-against-ngram adjusted p
would grow. It did, and nobody can report that as a change in the underlying
result, because the file said it would happen.

**The language model's threshold block.** `load_thresholds("llm")` raised, by
design since P4. The decision procedure in `audit/engine.py` is engine-agnostic
by confidence value, so the engine needed two floats; spec section 12.1 says a
self-reported confidence never feeds the threshold policy, so it must not be
gated by them. The only pair satisfying both is zero and zero.

That has two unflattering consequences and both were written down before the run:
the language model gets no threshold protection and accuses on every committed
prediction, and `LOW_CONFIDENCE` becomes unreachable for it. The alternative,
deriving a boundary on the self-reported scale against a precision target the way
P4 did, would probably have raised its finding-level precision. That it would
have flattered the engine is exactly why it had to be refused before the
measurement rather than after.

### The one drop that decides whether the benchmark measures anything

Spec section 12.2 requires the declared `autocomplete` value to be dropped from
the pruned descriptor, because leaving it in lets the model read the answer off
the page on every clean-tier form.

The obvious check is a substring search for the declared token in the serialised
payload, and it is wrong in both directions. A field named `email` that also
declares `autocomplete="email"` would trip it, and that combination is common
enough in a clean-tier corpus that it would have fired on the first real run and
been switched off. Meanwhile a declaration reaching the payload through some
derived value would not trip it at all.

So the property checked is **independence**: pruning the descriptor and pruning
the same descriptor with its declaration stripped must produce identical
payloads. That has neither failure mode, and it is asserted on every request
rather than reviewed once.

### The keep list is a floor, not a ceiling

Spec section 12.2 lists what pruning keeps and does not mention `pattern`,
`maxlength`, `required`, `readonly`, or the frame and shadow flags.
`classify/features.py` feeds every one of them to the n-gram model.

Withholding a signal one engine has from the other would tilt the comparison
exactly as far as handing over the whole document would, in the opposite
direction and with a better conscience. So the rule applied is that the language
model sees what the featuriser sees and nothing more, and the three named drops
stand because none of them reaches the featuriser either. Recorded here because
it is a deviation from a literal reading of the specification's list, taken for
the reason the specification gives for having the list at all.

## 2026-08-26: P6, what the benchmark measured

### The serving route worked on the first rung

Ollama was installed on the Windows host with the model already pulled, and
Windows Ollama binds loopback only, so from WSL2 the 7.5 GB blob was visible on
disk and unreachable over the network. Installing Ollama inside WSL2 and pointing
`OLLAMA_MODELS` at the Windows store reused the blob with no re-pull. It loads
<!-- traceability: a hardware reading from ollama ps and nvidia-smi, recorded in ADR 0007, not a result-file measurement -->
entirely on the GPU with about 3 GB of headroom at the benchmark's context length.
No step of the spec section 3.4 fallback ladder was taken and no row is labelled
`cpu-offload`. The details are in `adr/0007-llm-model-and-quantization.md`.

The one thing worth repeating here is the keep-alive policy. A long keep-alive
holds three quarters of a 12 GB card for as long as it lasts, and what it buys is
a model load costing under a minute. Ten minutes, and an explicit unload when a
run finishes. Every latency figure is taken against a warmed session, so the
reload costs nothing methodologically as long as the warm-up precedes the timing.

### The engine order in the benchmark is a methodological choice

`--engines llm,rules,ngram`, not the order the table is presented in. The two
classical engines take about two and a quarter minutes each of browser time with
no inference call in them, so running the language model last would have meant
roughly seven idle minutes before its first call, against a ten-minute
keep-alive. A keep-alive expiry inside a measured run would have put a cold model
load into the per-field latency distribution. Warming immediately before and
running it first avoids measuring the disk.

### The result

The language model came third. It lost to both classical engines on macro-F1, on
micro-F1, on every tier, and on the seen locales, and most of those margins are
certified after correction across the family of thirty-three. It led the n-gram
model on the held-out locale and that difference did not survive correction.

Spec section 13.4 asks whether a fifty-kilobyte linear model gets close enough to
a twelve-billion-parameter model to be the right default. The premise did not
survive: the linear model did not have to get close, because it won. The answer
is in `report.md` with the numbers and with the limits that go with it, and the
limits matter, because the classical engines were fitted on this corpus's
training split and the language model met it for the first time at inference.

### Four of the eight predictions were wrong, and the wrong ones were informative

The hostile tier and the unseen locale were where broad pretrained knowledge was
supposed to help. The hostile tier is where all three engines are worst and where
none of the differences is significant. The unseen locale is the one slice the
language model led on, and it could not be certified.

**Schema compliance was perfect**, which was not predicted. The registered
prediction was above zero and below five percent of requests needing a retry. Not
one did, across every request of the run. Passing the JSON schema with the request
and letting the server constrain decoding appears to remove the failure mode
outright. The retry ladder is still there and still tested against twelve
recorded transcripts including deliberately malformed ones; on this run it never
fired. A benchmark whose most interesting failure mode did not occur is a result,
and the honest report of it is the zero rather than a note about robustness.

**Abstention went the other way from the prediction.** The system prompt tells the
model to answer `UNKNOWN` when the evidence is insufficient and not to guess. It
abstained less than either classical engine and was right less often when it
committed. Instructing a model to decline is not equivalent to giving it a
threshold, and this is the measurement of that gap.

The confusion prediction was wrong in direction. The failure was expected to be
over-claiming, fields that are not personal data read as though they were. The
largest single confusion is the reverse: fields whose answer key is `UNKNOWN`
read as `NOT_AUTOFILLABLE`.

### The two classical engines reproduced their previous run exactly

Every prediction and every finding, field for field across all 2317 fields, and
every metric bit-identical. Only the latency columns differ, because those are
re-measured rather than recomputed. That was not the point of re-running them,
but it is the strongest reproducibility evidence this project has produced and it
is worth the sentence.

### One thing the harness does that the benchmark had to pay for twice

`scripts/eval.py` classifies every form twice: once directly, which is where the
run log's `pred_label` and the per-field latency come from, and once through
`audit.engine.audit`, which is where the finding codes come from. For the two
deterministic engines the passes agree by construction and cost microseconds. For
the language model it doubles the inference: the run made twice as many requests
as there are forms, and about half its wall clock is the audit pass.

It also means the label on a row and the finding codes beside it come from two
different draws of a model that spec section 12.3 point 7 says is not guaranteed
to be deterministic. Measured on the run, using the deterministic rule engine as a
control for the check's own edge cases, the language model's excess disagreement
between the two passes is on the order of two fields in seven hundred. Small,
real, and worth knowing before anyone builds on the finding-level numbers.

This is not fixed here. Fixing it means changing what `eval` does to every engine,
and doing that after seeing the results is the regeneration spec section 18
forbids. It is written down for P7 instead.

## 2026-08-27: P7, the documentation set and the three reports

The phase that turns six phases of work into something a reader who was not here
can check. No behaviour changed: the classifiers, the audit engine, the
thresholds and the renderers do exactly what they did at `0.4.0`, and the only
change to shipped output is the version string, which is what the nine-file
golden diff shows and is the evidence for the claim.

### The tag is not applied, and that is the phase's headline

**Version `1.0.0` is in code and in the changelog. There is no `v1.0.0` git tag
and no GitHub release.**

The build specification forbids tagging a stable release here while any
dependency is a git ref rather than a released version. `ml-experiment-triage` is still not
published to a package index. That rule was written on the first day of this
project, the obstacle was discovered on the same day and filed in
`cross-repo-tasks.md` with status open, and ADR 0001 recorded it while it was
fresh.

It is now the only thing standing between this repository and its first stable
tag, and it holds. The cheap way out has been available since P5 and is refused
again here: vendoring the three functions this project actually uses would remove
the blocker in half an hour and would delete the evidence the boundary exists to
produce. A rule that only binds when it is convenient is not a rule, and the
whole second-consumer claim of ADR 0004 rests on this one holding.

Tagging is a separate, later act once the dependency resolves. Everything else in
the definition of done is complete.

### Two mechanisms this phase had to invent, both because a rule collided with a requirement

**The dash rule against command-line flags.** Ground rule 13 forbids the two dash
codepoints everywhere and forbids the LaTeX ligature forms in `.tex` sources as
well, because those typeset to exactly the characters the rule bans.
`check_dashes.py` therefore rejects any run of two or more adjacent hyphens in a
`.tex` file. The reports have to show flags, and a flag is two hyphens.

Resolved in source rather than by exemption: a macro that inserts an empty group
between the two hyphens, so the source never carries the adjacent pair and the
typeset page carries exactly two hyphen glyphs. Inside verbatim blocks the same
macro is reachable because the environment declares the backslash and braces as
command characters. Documented once, at the top of `report/preamble.tex`, so that
a reader of a chapter does not have to reconstruct why the source looks that way.

**The traceability rule against a document that is mostly numbers.** Law 3
forbids a hand-typed number in any report, and `check_traceability.py` scans
`report/`, `report_debug/` and `report_for_me/` for anything shaped like a
measurement.

Resolved in two layers. Every table is generated by
`scripts/make_report_tables.py` from committed result files, and every emitted
line carrying a digit ends in a LaTeX comment naming the file the digit came
from, which is invisible on the page and visible to the checker. And the same
script emits `report/tables/values.tex`, one macro per number the prose quotes,
beside the path it was read from, so **the chapters of all three reports contain
no digits at all**. Editing a number by hand in a chapter is not a policy
violation somebody might notice at review. It is a red gate.

One collision inside that: an HTML-comment traceability annotation cannot appear
in a `.tex` file, because the opening and closing markers both contain two
adjacent hyphens. The two checks are therefore mutually exclusive on that
mechanism, which is why the generated tables clear the check with a
`% results: path` comment instead. That is the checker's own second clearing
rule and it names a real committed file, so it is a citation rather than a
waiver.

### The report deliverable paths, and a specification that disagrees with itself

Spec section 17.2 names the main report's deliverable as `report/build/main.pdf`.
Section 17.3 names the debug report's as `report_debug/debug_report.pdf`. Those
are two different conventions, and the `.gitignore` committed at P0 ignores
`report/build/` and `report_debug/build/` while saying in its own comment that
the compiled PDFs are committed.

Taken literally, the main report's deliverable would sit inside an ignored
directory and would need a negation rule to be committed at all, while the debug
report's would not.

Resolved with `latexmk -auxdir=build`: every auxiliary file goes to each report's
own `build/` directory, which stays ignored, and the compiled PDF is left beside
its source, where it is committed. The two deliverables then sit at symmetric
paths, `report/main.pdf` and `report_debug/debug_report.pdf`, both render
directly in the GitHub web interface, and neither needs an exception in the
ignore file. Recorded here because it is a deviation from a literal reading of
one section, taken to satisfy the other section and the ignore file at the same
time.

### The demo animation is rendered rather than recorded

Spec section 21 asks for a demo above the fold, produced from a committed fixture
so that it is reproducible, and regenerated rather than hand-edited.

A terminal recorder captures wall clock timings, so two runs of the same command
produce two different artefacts and a committed asset can never be reproduced
byte for byte. It also adds a binary that is not in the lock file to the set of
things a contributor needs before they can regenerate a committed asset.

So `scripts/make_demo_gif.sh` runs the tool for real against the hostile
checkout fixture, captures its stdout and its exit status, and hands both to a
renderer that draws the transcript as frames with Pillow, which arrives with
matplotlib and is therefore already in the lock file. Nothing in the animation is
written by hand; only its length is trimmed, and the trim is marked on screen so
nobody reads the shortened list as the whole report. The script fails if the
hostile fixture ever exits clean, because a demo of a tool that has stopped
finding what it exists to find is advertising a defect.

It demonstrates the rule engine rather than the strongest engine that loads, and
that is honesty rather than preference: a published wheel carries no model, so
the rule engine is what a reader who installs the tool in the next five minutes
will actually see.

### Three ADRs written late, and said so

`0002`, `0003` and `0004` were missing. The decisions they record were made at
P1, P3 and P5 and were acted on consistently, but the records were not written
when the decisions were made, which is what the specification asks for.

They are written now from recorded evidence rather than from memory: the taxonomy
module and its group partition, the reachability check's clauses, the phase order
and its tags in the changelog, the per-engine threshold blocks, the ledger with
its five issue links, the `dev`-extra placement and its comment, the mypy
override, and the `harness` and `harness_cross_check` blocks in every committed
analysis file. Each ADR opens with a note saying it was recorded at P7, naming
the phase the decision belongs to and the artefacts it was reconstructed from.

The lateness is the defect and the note is the record of it. Backdating them
would have been the other option and it is exactly the kind of small dishonesty
this project's laws exist to rule out.

### What the reports say that the project would rather not

Written down here because a write-up phase is where a project gets quietly
flattering, and the specific temptations were foreseeable.

**The answer to the section 13.4 question is that the linear model won**, not
that it got close enough. The specification anticipated a world where the
language model wins on the hostile tier and the held-out locale and told the
write-up to be willing to print either outcome. It printed the other one.

**Four of eight predictions were wrong and the write-up leads with two of them.**
Schema compliance was perfect where failures were predicted, and abstention went
below both classical engines where it was predicted to land between them. Both
are more interesting than the four that held.

**The nine wrong accusations are in the main report and in `report.md`**, named
as the first time an engine in this project told a developer to add a token the
answer key disagrees with, and explained as the threshold policy working rather
than failing.

**The training manifest of the shipped model is marked dirty**, and that now
opens the model card rather than sitting in a file nobody opens. It is in the
main report's method chapter, in its limitations chapter, in the debug report's
open-items chapter and in `report.md`. What follows from it is bounded and is
stated precisely rather than either ignored or overstated: the model artefacts
and the corpus are content-addressed into every evaluation manifest, so what was
measured is not in doubt, and what is weaker is the dev-split evidence. It is not
repaired, because refitting now would produce a different model from the one
every committed result was measured against.

**The double classification in `eval.py` is documented as a known limitation**
with its measured magnitude, in the main report, the debug report, `report.md`
and the changelog, and it is not fixed. Fixing it changes what the runner does
for every engine and doing that after seeing the results is the regeneration the
reproducibility rules forbid. The fix belongs to a phase that re-registers first
and then measures again.

### The personal report stays local

`report_for_me/` is built completely, all six numbered sections, source and PDF,
and it is gitignored and is not committed. That overrides the specification's own
line about committing it, on the author's standing instruction, and it was
recorded at P0 for exactly this reason: so that a reader of the definition-of-done
checklist would not find one box that can never be ticked with no explanation.

It is the longest of the three documents and the two chapters that overlap the
debug report are deliberately unedited where the debug report is edited. That
overlap is the point rather than waste: one is the public thematic version and
one is the complete one, and the engineering log is the shared source both draw
from. This entry is the last thing that log receives before both were written,
which is the only order in which the log discipline pays for itself.

### Gates

- `make reports-clean` then `make reports`: all three PDFs built from nothing,
  with the tables and figures regenerated from committed result files first.
- `make gates` green: ruff, the dash check over every tracked file including the
  LaTeX sources, mypy strict, pytest with the coverage gate, reachability,
  traceability in resolving mode, prediction ancestry.
- The traceability check resolves every citation in the README, in `docs/` and in
  all three reports' sources through a manifest to a commit object this
  repository can produce.
- The dash check passes over the `.tex` sources including the ligature forms.
- `git tag -l` shows no `v1.0.0`, which is the gate for this phase rather than a
  step that was forgotten.

### What P8 would need

If the transformer stretch is taken, the plumbing is already there and the
expensive part is the training data question. The export path exists and is
tested, the parity gate generalises, `thresholds.json` already takes a block per
engine and raises for an engine without one, the run-log schema already carries
what a fourth engine needs, `bench` already accepts a list of engines, and the
report table generator reads its engine list from one tuple. Two things need a
deliberate new entry rather than a default: the confidence-kind mapping in
`evaluate/runlog.py`, which is total and raises on an unknown word, and the
`absent` row in `benchmark.json` that currently carries the fourth engine's name
and the sentence explaining it.

The condition for shipping it does not move: it ships only if it beats a
pre-stated metric by a pre-stated margin within a pre-stated latency budget, and
if it does not, the deliverable is the paragraph saying so with the numbers.

## 2026-08-27: the v1.0.0 tag, applied by direction

The P7 entry above records why the tag was withheld: the dependency contract in
the build specification forbids a stable tag while any dependency is a git ref,
and `ml-experiment-triage` is one.
The project owner has directed that the tag be applied now, with the pin in
place, because the index publication will not happen for a while and the stable
tag is needed on the repository today.

Applied as directed. The deviation is recorded in `docs/cross-repo-tasks.md`
beside the rule it deviates from, which is where a reader checking the rule will
find it. Nothing else about the release changes: the tree at the tag is the P7
tree, the gates were green on it, and the publication task remains open.
