"""The three renderers: terminal, JSON, and single-file HTML.

A renderer formats findings and nothing else. It never changes a severity, never
decides whether a finding fires, and never formats a confidence its own way: the
audit engine has already decided all three and put the results on the ``Finding``
(spec section 5.1). That is what makes the three agree, and what makes a
disagreement between them a diff in one of the golden snapshots rather than
something somebody notices in a screenshot six months later.
"""

from autofill_audit.report import html_report, json_report, terminal

__all__ = ["html_report", "json_report", "terminal"]
