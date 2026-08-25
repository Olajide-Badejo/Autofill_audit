"""The ``LLMClient`` interface, a local Ollama client, and a config-swap cloud client.

Filled at P6 (spec section 12.1). One interface in front of every backend, so
that changing model or host is configuration rather than a refactor.
"""
