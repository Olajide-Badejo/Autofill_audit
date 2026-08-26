"""The pluggable LLM client and the versioned prompt contract.

Spec section 12. Nothing here is required to run the tool, the tests, or CI
(ground rule 11), and nothing in the audit path imports it.

``httpx`` is the project's one optional dependency and it is imported inside
``client.HttpxTransport.send`` rather than at module scope, so importing this
package on an installation that never asked for the research layer works and
fails only at the point something actually tries to reach a server. That is the
right place for it to fail: the message names the extra to install, and the
whole client is testable against recorded transcripts without it.
"""
