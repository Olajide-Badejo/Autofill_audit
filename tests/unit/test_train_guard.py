"""The training script's test-partition guard, and the contract around it.

Spec section 10.3 asks for an assertion that raises if a test-partition path is
opened during training, and says the small ugliness is worth it because every
project intends not to touch its test set and a meaningful fraction of them do
anyway.

The armed hook is exercised in a subprocess. ``sys.addaudithook`` cannot be
removed for the life of the process, so arming it inside the test session would
leave every later test running under a hook this module installed, which is a
worse failure mode than the one being tested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import train


def _guard() -> train.TestPartitionGuard:
    return train.TestPartitionGuard(frozenset({"payment-03-en-US-hostile-v0"}))


def test_a_test_partition_path_is_refused_by_name() -> None:
    """The check every corpus path goes through before anything opens it."""
    with pytest.raises(train.TestPartitionError, match="test partition"):
        _guard().check(Path("corpus/forms/payment-03-en-US-hostile-v0.html"))


def test_the_matching_answer_key_is_refused_too() -> None:
    """A key and a form share a stem, so one rule covers both."""
    with pytest.raises(train.TestPartitionError):
        _guard().check("corpus/answer_keys/payment-03-en-US-hostile-v0.json")


def test_a_train_partition_path_passes() -> None:
    """The guard is narrow: it refuses the test partition and nothing else."""
    _guard().check(Path("corpus/forms/login-01-en-US-clean-v0.html"))


def test_the_error_says_why_rather_than_only_what() -> None:
    """A guard that only said no would be a guard somebody removed."""
    with pytest.raises(train.TestPartitionError) as caught:
        _guard().check("payment-03-en-US-hostile-v0.html")
    assert "no legitimate reason" in str(caught.value)


def test_the_armed_hook_raises_on_a_real_open(tmp_path: Path) -> None:
    """The backstop: a read nothing routed through ``check`` still raises.

    This is the case the guard exists for. ``check`` covers the paths the script
    resolves; the audit hook covers the line somebody adds later.
    """
    forbidden = tmp_path / "payment-03-en-US-hostile-v0.json"
    forbidden.write_text("{}", encoding="utf-8")
    program = (
        "import sys, json;"
        f"sys.path.insert(0, {str(Path(train.__file__).parent)!r});"
        "import train;"
        "guard = train.TestPartitionGuard(frozenset({'payment-03-en-US-hostile-v0'}));"
        "guard.arm();"
        f"open({str(forbidden)!r}, encoding='utf-8').read()"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert completed.returncode != 0
    assert "TestPartitionError" in completed.stderr


def test_an_allowed_open_still_works_once_armed(tmp_path: Path) -> None:
    """The hook must not break the training run it is protecting."""
    allowed = tmp_path / "login-01-en-US-clean-v0.json"
    allowed.write_text(json.dumps({"ok": True}), encoding="utf-8")
    program = (
        "import sys, json;"
        f"sys.path.insert(0, {str(Path(train.__file__).parent)!r});"
        "import train;"
        "guard = train.TestPartitionGuard(frozenset({'payment-03-en-US-hostile-v0'}));"
        "guard.arm();"
        "guard.arm();"
        f"print(open({str(allowed)!r}, encoding='utf-8').read())"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert "true" in completed.stdout.lower()


def test_the_train_command_line_has_no_test_flag() -> None:
    """Spec section 14 states it as a contract rather than as an omission."""
    parsed = train._arguments(["--seed", "1", "--out", "somewhere"])
    assert not hasattr(parsed, "test")
    with pytest.raises(SystemExit):
        train._arguments(["--seed", "1", "--out", "somewhere", "--test", "corpus/test"])


def test_the_excluded_partition_is_documented_as_unused() -> None:
    """P1's fourth partition is used for nothing at P4, and the script says so."""
    assert train.__doc__ is not None
    assert "used for\nnothing" in train.__doc__ or "used for nothing" in train.__doc__
    assert train.EXCLUDED == "excluded"
