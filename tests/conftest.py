"""Test configuration.

The CI scripts under ``scripts/`` are executable checks rather than library
modules, so they are not importable from the installed package. Putting the
directory on ``sys.path`` here lets the test suite exercise them as code instead
of shelling out to them, which is what makes their failure paths testable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SAMPLE_CORPUS = REPO_ROOT / "tests" / "fixtures" / "sample_corpus"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for tests that read committed files."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def sample_corpus() -> Path:
    """The committed sample corpus directory."""
    return SAMPLE_CORPUS
