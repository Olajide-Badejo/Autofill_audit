"""Shared fixtures for the LLM suite: transcripts, descriptors, and a built client.

Every test in this directory is network-free. Spec section 15 puts the live
server behind an environment variable and a reachability check, and
``test_live.py`` is the only module that looks for one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from autofill_audit.descriptors import FieldDescriptor
from autofill_audit.llm.client import LLMConfig, OllamaClient, RecordedTransport
from builders import make_descriptor

TRANSCRIPTS = Path(__file__).resolve().parents[1] / "fixtures" / "llm"


@pytest.fixture(scope="session")
def transcripts() -> Path:
    """The committed transcript directory."""
    return TRANSCRIPTS


def load_transcript(name: str) -> dict[str, Any]:
    """Read one committed transcript document."""
    payload: dict[str, Any] = json.loads((TRANSCRIPTS / f"{name}.json").read_text(encoding="utf-8"))
    return payload


def descriptors_for(selectors: Sequence[str]) -> list[FieldDescriptor]:
    """Build one descriptor per selector, with plausible but irrelevant signals.

    The signals do not matter to any test here: the transcript decides what comes
    back. What matters is that the selectors are the ones the transcript answers,
    because the selector is the join key the semantic validation of spec section
    12.3 point 2 checks.
    """
    labels = ("First name", "Postal code", "Search this site")
    names = ("fname", "plz", "q")
    return [
        make_descriptor(
            selector=selector,
            label=labels[index % len(labels)],
            name=names[index % len(names)],
            document_index=index,
        )
        for index, selector in enumerate(selectors)
    ]


def client_for(
    name: str, *, config: LLMConfig | None = None
) -> tuple[OllamaClient, list[FieldDescriptor], RecordedTransport]:
    """Build a client wired to one committed transcript.

    Returns the transport too, because several tests assert on what was *sent*:
    that the schema travelled with the request, that the declaration did not, and
    that the retry message named the right selectors.
    """
    document = load_transcript(name)
    responses: list[Mapping[str, Any]] = list(document["responses"])
    transport = RecordedTransport(responses)
    client = OllamaClient(config or LLMConfig(), transport)
    return client, descriptors_for(document["selectors"]), transport


@pytest.fixture
def compliant() -> tuple[OllamaClient, list[FieldDescriptor], RecordedTransport]:
    """A client whose single recorded response answers everything."""
    return client_for("compliant")
