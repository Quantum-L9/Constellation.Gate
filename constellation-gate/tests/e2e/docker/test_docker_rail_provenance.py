"""The Docker rail's provenance contract, exercised without Docker.

A rail PASS is only evidence when it is bound to exact, clean sources and to
the one SDK commit Gate's lock names. These tests prove each bypass the audit
found is now a failure: a dirty or unexpected checkout, a lock that resolves
to zero or several SDK commits, an image built from another revision, and an
SDK in the Gate image that is not the locked one.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parent / "scripts"
GATE_LOCK = Path(__file__).resolve().parents[3] / "requirements.lock"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"docker_rail_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


provenance = _load("provenance")
assert_evidence = _load("assert_evidence")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _workspace(root: Path) -> dict[str, str]:
    """Three clean single-commit checkouts named like the release set."""
    heads: dict[str, str] = {}
    for node, (directory, _env) in provenance.RELEASE_SET.items():
        repo = root / directory
        repo.mkdir(parents=True)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "ci@example.com")
        _git(repo, "config", "user.name", "ci")
        (repo / ".gitignore").write_text("ignored/\n")
        (repo / "app.py").write_text(f"NODE = {node!r}\n")
        _git(repo, "add", ".gitignore", "app.py")
        _git(repo, "commit", "-qm", "init")
        heads[node] = _git(repo, "rev-parse", "HEAD")
    return heads


# ------------------------------------------------------------------- sources


def test_clean_workspace_passes(tmp_path: Path) -> None:
    heads = _workspace(tmp_path)
    receipt = provenance.check_sources(tmp_path, {})
    assert receipt["verdict"] == "PASS"
    assert {n: r["head"] for n, r in receipt["nodes"].items()} == heads


def test_ignored_files_do_not_count_as_dirty(tmp_path: Path) -> None:
    _workspace(tmp_path)
    ignored = tmp_path / "Constellation.Gate" / "ignored"
    ignored.mkdir()
    (ignored / "evidence.json").write_text("{}\n")
    assert provenance.check_sources(tmp_path, {})["verdict"] == "PASS"


@pytest.mark.parametrize("change", ["modified", "untracked", "staged"])
def test_a_dirty_checkout_fails(tmp_path: Path, change: str) -> None:
    _workspace(tmp_path)
    repo = tmp_path / "Cognitive.Engine.Graphs"
    if change == "modified":
        (repo / "app.py").write_text("NODE = 'tampered'\n")
    elif change == "untracked":
        (repo / "extra.py").write_text("x = 1\n")
    else:
        (repo / "staged.py").write_text("x = 1\n")
        _git(repo, "add", "staged.py")
    receipt = provenance.check_sources(tmp_path, {})
    assert receipt["verdict"] == "FAIL"
    assert any("dirty worktree" in v for v in receipt["nodes"]["ceg"]["violations"])


def test_an_unexpected_head_fails_and_the_expected_one_passes(tmp_path: Path) -> None:
    heads = _workspace(tmp_path)
    wrong = provenance.check_sources(tmp_path, {"L9_E2E_EXPECT_EIE_SHA": SHA_A})
    assert wrong["verdict"] == "FAIL"
    assert any("is not the expected" in v for v in wrong["nodes"]["eie"]["violations"])

    right = provenance.check_sources(tmp_path, {"L9_E2E_EXPECT_EIE_SHA": heads["eie"]})
    assert right["verdict"] == "PASS"


def test_a_missing_checkout_fails(tmp_path: Path) -> None:
    _workspace(tmp_path)
    receipt = provenance.check_sources(tmp_path / "elsewhere", {})
    assert receipt["verdict"] == "FAIL"


def test_sources_cli_fails_closed_and_still_writes_the_receipt(tmp_path: Path) -> None:
    _workspace(tmp_path)
    (tmp_path / "Constellation.Gate" / "dirt.txt").write_text("x\n")
    out = tmp_path / "receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "provenance.py"),
            "sources",
            "--workspace",
            str(tmp_path),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert json.loads(out.read_text())["verdict"] == "FAIL"


# ------------------------------------------------------------------ SDK lock


def _sdk_line(sha: str) -> str:
    return (
        f"constellation-node-sdk @ https://github.com/Quantum-L9/Gate_SDK/archive/{sha}.tar.gz"
        " --hash=sha256:" + "0" * 64
    )


def test_the_real_gate_lock_resolves_to_one_sdk_commit() -> None:
    assert provenance.FULL_SHA.match(provenance.sdk_lock_sha(GATE_LOCK.read_text()))


def test_one_archive_line_resolves() -> None:
    assert provenance.sdk_lock_sha(f"anyio==4.15.0\n{_sdk_line(SHA_A)}\n") == SHA_A


@pytest.mark.parametrize(
    ("lock", "message"),
    [
        ("anyio==4.15.0\n", "found 0"),
        (f"{_sdk_line(SHA_A)}\n{_sdk_line(SHA_B)}\n", "found 2"),
        (
            "constellation-node-sdk @ git+https://github.com/Quantum-L9/Gate_SDK.git@v1\n",
            "not a Gate_SDK archive commit URL",
        ),
    ],
)
def test_a_lock_without_exactly_one_sdk_commit_fails(lock: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        provenance.sdk_lock_sha(lock)


def test_build_images_has_no_fallback_sdk_sha() -> None:
    body = (SCRIPTS / "build_images.sh").read_text()
    assert "L9_E2E_GATE_SDK_SHA" not in body
    assert "lock_sha:-" not in body
    assert 'provenance.py" sources' in body


def test_vendoring_never_reuses_a_cached_tree() -> None:
    body = (SCRIPTS / "vendor_gate_sdk.sh").read_text()
    assert "reusing" not in body
    assert ".complete" not in body


# ------------------------------------------------------------------- verdict


def _bundle(
    ev: Path,
    heads: dict[str, str],
    *,
    images: dict[str, str | None] | None = None,
    lock_sha: str = SHA_A,
    source_verdict: str = "PASS",
) -> None:
    ev.mkdir(parents=True, exist_ok=True)
    nodes = {n: {"head": h, "violations": []} for n, h in heads.items()}
    (ev / "source_revisions.json").write_text(
        json.dumps({"verdict": source_verdict, "nodes": nodes})
    )
    (ev / "image_revisions.json").write_text(json.dumps(images if images is not None else heads))
    (ev / "sdk_lock.json").write_text(json.dumps({"lock_sha": lock_sha}))


HEADS = {"gate": "1" * 40, "eie": "2" * 40, "ceg": "3" * 40}


def test_verdict_binds_images_sources_and_the_locked_sdk(tmp_path: Path) -> None:
    _bundle(tmp_path, HEADS)
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_A})
    assert set(results.values()) == {"PASS"}, results


def test_an_image_built_from_another_revision_fails(tmp_path: Path) -> None:
    _bundle(tmp_path, HEADS, images={**HEADS, "eie": "9" * 40})
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_A})
    assert results["PROVENANCE_images_bound"] == "FAIL"


def test_an_unlabelled_image_fails(tmp_path: Path) -> None:
    _bundle(tmp_path, HEADS, images={**HEADS, "ceg": None})
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_A})
    assert results["PROVENANCE_images_bound"] == "FAIL"


def test_a_gate_sdk_that_is_not_the_locked_commit_fails(tmp_path: Path) -> None:
    _bundle(tmp_path, HEADS, lock_sha=SHA_A)
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_B})
    assert results["SDK_gate_matches_lock"] == "FAIL"


def test_dirty_sources_fail_the_verdict(tmp_path: Path) -> None:
    _bundle(tmp_path, HEADS, source_verdict="FAIL")
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_A})
    assert results["PROVENANCE_sources_clean"] == "FAIL"


def test_missing_provenance_receipts_fail(tmp_path: Path) -> None:
    results = assert_evidence.provenance_results(tmp_path, {"gate": SHA_A})
    assert set(results.values()) == {"FAIL"}, results
