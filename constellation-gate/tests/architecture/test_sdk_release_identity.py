"""The SDK release-identity validator must discriminate, not just pass.

`scripts/validate_sdk_pin.py` is the only thing standing between Gate and a
repeat of the drift it was written for: two active declarations naming two
different Gate_SDK commits, both looking deliberate. A validator that passes
the current tree proves nothing on its own, so these tests drive the failure
side — sha, branch, fork, missing surface, stale lock — through the pure
functions.

No test here touches the network. The `--verify-tag` comparison is exercised
as pure logic; `resolve_remote_tag` is the only networked part and it is
deliberately kept to one line of its own.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / "scripts" / "validate_sdk_pin.py"

_SPEC = importlib.util.spec_from_file_location("validate_sdk_pin", VALIDATOR)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"{VALIDATOR} did not load")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

check_manifest = _MOD.check_manifest
check_lock = _MOD.check_lock
check_tree = _MOD.check_tree
lock_resolution = _MOD.lock_resolution
compare_lock_to_tag = _MOD.compare_lock_to_tag

CHANNEL_OBJECT = "e9f829f982110be13752da8f18c7a9692e8ed908"
OTHER_OBJECT = "2b2f53a28a59bbfb2fa45f5eac32b722d802209a"
ARCHIVE_DIGEST = "e" * 64

PYPROJECT_V1 = '  "constellation-node-sdk @ git+https://github.com/Quantum-L9/Gate_SDK.git@v1",\n'
PRECOMMIT_V1 = (
    "          - constellation-node-sdk @ git+https://github.com/Quantum-L9/Gate_SDK.git@v1\n"
)
LOCK_LINE = (
    f"constellation-node-sdk @ https://github.com/Quantum-L9/Gate_SDK/archive/"
    f"{CHANNEL_OBJECT}.tar.gz --hash=sha256:{ARCHIVE_DIGEST}\n"
)


# ------------------------------------------------------------------ manifests


def test_the_moving_major_channel_passes() -> None:
    assert check_manifest("pyproject.toml", PYPROJECT_V1) == []
    assert check_manifest(".pre-commit-config.yaml", PRECOMMIT_V1) == []


def test_a_commit_sha_declaration_fails() -> None:
    text = PYPROJECT_V1.replace("@v1", f"@{CHANNEL_OBJECT}")
    errors = check_manifest("pyproject.toml", text)
    assert any("commit sha" in item for item in errors), errors


def test_the_exact_release_tag_is_not_the_consumer_contract() -> None:
    """v1.1.0 is an immutable release label; consumers declare the channel."""
    text = PYPROJECT_V1.replace("@v1", "@v1.1.0")
    errors = check_manifest("pyproject.toml", text)
    assert any("not 'v1'" in item for item in errors), errors


@pytest.mark.parametrize("branch", ["main", "master"])
def test_a_floating_branch_fails(branch: str) -> None:
    text = PYPROJECT_V1.replace("@v1", f"@{branch}")
    errors = check_manifest("pyproject.toml", text)
    assert any("floats on branch" in item for item in errors), errors


def test_the_forbidden_fork_fails() -> None:
    text = PYPROJECT_V1.replace("Quantum-L9/Gate_SDK", "cryptoxdog/Gate_SDK")
    errors = check_manifest("pyproject.toml", text)
    assert any("forbidden fork" in item for item in errors), errors


def test_a_manifest_with_no_sdk_declaration_fails() -> None:
    errors = check_manifest("pyproject.toml", '  "fastapi>=0.115.0",\n')
    assert any("no Quantum-L9/Gate_SDK declaration" in item for item in errors), errors


# ----------------------------------------------------------------------- lock


def test_the_lock_must_carry_a_concrete_hash_verified_archive() -> None:
    assert check_lock("requirements.lock", LOCK_LINE) == []
    assert lock_resolution(LOCK_LINE) == CHANNEL_OBJECT


def test_an_unhashed_git_lock_entry_fails() -> None:
    unhashed = "constellation-node-sdk @ git+https://github.com/Quantum-L9/Gate_SDK.git@v1\n"
    errors = check_lock("requirements.lock", unhashed)
    assert any("hash-verified" in item for item in errors), errors
    assert lock_resolution(unhashed) is None


# ------------------------------------------------------- surface enumeration


def test_a_missing_active_surface_fails(tmp_path: Path) -> None:
    """A surface that stops being enumerated is how the drift went unnoticed."""
    gate = tmp_path / "constellation-gate"
    gate.mkdir()
    (gate / "pyproject.toml").write_text(PYPROJECT_V1)
    # .pre-commit-config.yaml and requirements.lock deliberately absent.
    errors = check_tree(tmp_path)
    assert any(".pre-commit-config.yaml: active surface is missing" in e for e in errors), errors
    assert any("requirements.lock: generated lock is missing" in e for e in errors), errors


def test_a_complete_tree_passes(tmp_path: Path) -> None:
    gate = tmp_path / "constellation-gate"
    gate.mkdir()
    (gate / "pyproject.toml").write_text(PYPROJECT_V1)
    (gate / ".pre-commit-config.yaml").write_text(PRECOMMIT_V1)
    (gate / "requirements.lock").write_text(LOCK_LINE)
    assert check_tree(tmp_path) == []


def test_the_real_tree_declares_the_channel() -> None:
    assert check_tree(REPO_ROOT) == []


# ----------------------------------------------- stale-lock (--verify-tag logic)


def test_a_current_lock_agrees_with_the_channel() -> None:
    assert compare_lock_to_tag(CHANNEL_OBJECT, CHANNEL_OBJECT) == []


def test_a_stale_lock_fails() -> None:
    errors = compare_lock_to_tag(OTHER_OBJECT, CHANNEL_OBJECT)
    assert any("stale" in item for item in errors), errors


def test_an_unresolvable_channel_fails_closed() -> None:
    """Not a warning: a lock that cannot be checked has not been checked."""
    errors = compare_lock_to_tag(CHANNEL_OBJECT, None)
    assert any("could not resolve" in item for item in errors), errors


def test_a_lock_with_no_resolution_fails_closed() -> None:
    errors = compare_lock_to_tag(None, CHANNEL_OBJECT)
    assert any("no concrete resolved object" in item for item in errors), errors
