# Cloud list prices, for the config-swap client only

**Nothing in this project has ever been billed against these numbers, and no
result file in this repository contains a cost computed from them.** The headline
benchmark of spec section 13.4 ran entirely on a local model, and every cost cell
in it is `null`.

This table exists because spec section 12.4 requires that a cloud client's cost
be "a **list-price estimate** computed from a price table in `docs/` with its
retrieval date", labelled `estimated_cost_usd_list_price` in the schema and
rendered with the word "estimated". A price table with no table is not a
requirement that has been met, so here it is, with the retrieval date the
specification asks for and the caveats that make it honest.

## Retrieval

**Retrieved: not retrieved.** No vendor pricing page was fetched for this table,
because CI and the build machine are offline with respect to model providers
(spec section 16: CI "does not call any network service other than the package
index and the Playwright download host"), and because fetching a price to put in
a document that immediately calls it an estimate would add a date without adding
accuracy.

The consequence is stated rather than hidden: **the table below is empty of
prices.** The client accepts prices as constructor arguments and computes nothing
when they are absent, which is the same `null` the local path records and for the
same reason.

| Model | Input, USD per million tokens | Output, USD per million tokens | Retrieved |
|---|---|---|---|
| any hosted model | not configured | not configured | not retrieved |

## How a price gets used, if one ever is

The cloud client takes the two rates as arguments and multiplies them by the
token counts **as the provider reported them**:

```
estimated_cost_usd_list_price = (prompt_tokens * input_rate
                                 + completion_tokens * output_rate) / 1e6
```

Three properties of that number are load bearing and each is enforced somewhere
other than this document.

**It is a list price, not spend.** The field name says so, the client's
`describe()` carries `cost_basis: estimated list price, never observed spend`,
and law 4 requires the word "estimated" at the point of display. A list price
ignores volume discounts, committed-use pricing, caching discounts, free tiers,
and taxes, so it is an upper bound on one interpretation of the bill and not the
bill.

**It is computed from reported tokens, not from a tokenizer this project runs.**
If a provider reports no token counts, the counts are `None` and the estimate is
`None`. Guessing them with a local tokenizer would produce a number whose error
nobody could bound.

**It is never zero when it is unknown.** Spec section 12.4: local calls log
`null`, "not `0.0`, because zero is a measurement and null is the absence of
one". The same rule applies to a cloud call whose rates were never configured.

## Filling this in

If a later phase runs a hosted model, this document is the place the rates go,
each with the date its page was read, and the run manifest will carry the
resulting estimate under `estimated_cost_usd_list_price`. Until then the honest
content of a price table with no prices in it is a sentence saying so, which is
what this is.

A rate typed in from memory would be the worst available option: it would look
like a citation, it would resolve to nothing, and the cost column of a report
would carry a number whose provenance is somebody's recollection of a pricing
page. Law 3 exists to stop exactly that, and it applies to prices as much as to
metrics.
