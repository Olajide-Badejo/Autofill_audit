# References

Cited by stable descriptor and URL rather than by remembered title. Every entry
below was requested from this machine on the retrieval date and its response
status recorded; where a URL redirected, the destination is recorded and the
original is kept beside it so the move is visible rather than quietly rewritten.

Retrieval date for every entry: **2026-08-25**.

**Re-verified 2026-08-27**, at P7, before the bibliography of the compiled
reports was assembled from this file. Every entry above the literature section
answered `200` again from this machine and none had moved since the first
retrieval, so the addresses below are unchanged. The one entry whose status is
not `200` is the journal article, and it behaves exactly as it did at P0: the
DOI resolver redirects and the publisher answers `403` to an automated request.
That is a robot policy rather than a broken link and it is recorded that way.

The re-verification matters because the bibliography in
[`../report/refs.bib`](../report/refs.bib) is assembled from this file and from
nothing else. A citation this project has not read appears in neither, and one
that has moved is recorded as having moved rather than quietly rewritten.

New references are added here when they are actually read, with their own
retrieval date, and never before. A citation this project has not read does not
appear in this file, in `docs/report.md`, or in any bibliography.

## Primary sources

**1. WHATWG HTML Living Standard, autofill section.** The normative definition
of the `autocomplete` attribute, the autofill field-name tokens, the shipping
and billing modifiers, the contact modifiers, `section-*`, and the autofill
anchor and expectation mantle algorithm. **This is the taxonomy's source of
truth and the single most important reference in the project.**
<https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#autofill>
Status: reachable, HTTP `200`.

**2. MDN, `autocomplete` attribute reference.** Practical per-token
documentation and browser support notes.
Requested: <https://developer.mozilla.org/en-US/docs/Web/HTML/Attributes/autocomplete>
Status: HTTP `301`, redirected. Current location, recorded rather than assumed:
<https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/autocomplete>

**3. web.dev, form best-practice guides.** The Chrome team's developer guidance
on form design, `autocomplete` usage, labels, and `inputmode`, and the source of
the argument that broken autofill is a conversion problem, not a cosmetic one.
<https://web.dev/learn/forms/> and the sign-in and payment-form articles under
<https://web.dev/>
Status: both reachable, HTTP `200`.

**4. Chrome for Developers documentation.** Chrome's own description of how
autofill selects and fills fields.
<https://developer.chrome.com/docs/>
Status: reachable, HTTP `200`.

**5. WAI-ARIA Authoring Practices, form labelling.** The basis for the label
association signal hierarchy the extractor uses.
<https://www.w3.org/WAI/ARIA/apg/>
Status: reachable, HTTP `200`.

## Tooling

**6. Playwright for Python documentation.** Synchronous API, frames, shadow DOM
piercing, waiting strategies, browser installation.
<https://playwright.dev/python/docs/intro>
Status: reachable, HTTP `200`.

**7. scikit-learn user guide.** Text feature extraction including the `char_wb`
analyser and n-gram ranges, logistic regression, and probability calibration.
<https://scikit-learn.org/stable/>
Status: reachable, HTTP `200`.

**8. skl2onnx documentation.** Converter reference, and the documented
limitations of the text vectorizer converters that the export phase plans
around.
<https://onnx.ai/sklearn-onnx/>
Status: reachable, HTTP `200`.

**9. onnxruntime documentation.** Python API, execution providers, threading
options, dynamic quantization.
<https://onnxruntime.ai/docs/>
Status: reachable, HTTP `200`.

**10. ONNX Runtime quantization guide.** Dynamic INT8 quantization for
transformer encoders, for the optional transformer phase.
<https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>
Status: reachable, HTTP `200`.

**11. Ollama documentation.** Model library, modelfile parameters, structured
outputs via JSON schema, and the OpenAI-compatible endpoint.
<https://github.com/ollama/ollama/blob/main/docs/api.md> and
<https://ollama.com/blog> for the structured-outputs announcement.
Status: both reachable, HTTP `200`.

**13. Faker documentation.** Locale providers and seeding.
Requested: <https://faker.readthedocs.io/>
Status: HTTP `302`, redirected. Current location:
<https://faker.readthedocs.io/en/master/>

**14. Stripe testing documentation.** The published test card numbers used in
payment fixtures, so that no fixture can carry a real card number.
<https://docs.stripe.com/testing>
Status: reachable, HTTP `200`.

**15. ML-Experiment-Triage.** The author's evaluation harness, consumed here as
a dependency rather than vendored.
<https://github.com/Olajide-Badejo/ML-Experiment-Triage>
Status: reachable, HTTP `200`.

**16. Keep a Changelog and Semantic Versioning.** The changelog format and the
versioning scheme this project follows.
<https://keepachangelog.com/> and <https://semver.org/>
Status: both reachable, HTTP `200`.

## Literature

**12. Benjamini, Y. and Hochberg, Y. (1995).** "Controlling the False Discovery
Rate: A Practical and Powerful Approach to Multiple Testing." *Journal of the
Royal Statistical Society, Series B*, volume `57`, issue `1`, pages `289` to
`300`. The multiple-comparison correction procedure used when the evaluation
phase compares engines across the locale and tier grid.
DOI: <https://doi.org/10.1111/j.2517-6161.1995.tb02031.x>
Status: the DOI resolver redirects to the publisher, which answered HTTP `403`
to an automated request from this machine. This is a publisher paywall and
robot policy rather than a broken link: the DOI itself resolves. Recorded
honestly rather than reported as reachable.

## Added at P7

**17. Matplotlib documentation.** The plotting library the report figure
generator uses. Read for the figure API and the vector output backend when
`scripts/make_report_figures.py` was written; it is a `dev` dependency and the
audit path never imports it.
<https://matplotlib.org/stable/>
Status: reachable, HTTP `200`. Retrieved 2026-08-27.

It is listed here rather than in `report/refs.bib` because it is a build tool for
this project's own figures rather than a source for any claim the reports make.
The bibliography is the reading list behind the argument; this entry belongs to
the toolchain.

## On fabricated citations

No entry appears in this file, or in any bibliography in this repository, unless
the source was actually retrieved and read. A plausible-looking citation to a
paper nobody opened is worse than no citation, because it survives review by
looking exactly like a real one.
