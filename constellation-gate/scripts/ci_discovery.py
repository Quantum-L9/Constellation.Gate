#!/usr/bin/env python3
"""
Generic fail-open CI error-discovery tool.

Runs the quality gates a typical Python project's CI/pre-commit pipeline
uses -- dependency install, pre-commit (autofix hooks + hooks with
isolated `additional_dependencies` environments), ruff, ruff-format,
mypy, pytest collection, tool-version drift, and any project-specific
scripts you configure -- in "fail-open" mode: a failure in one check
never stops the remaining checks from running. Emits a single
machine-readable JSON report mapping every discovered error back to its
source tool, file, and location.

This tool is repo-agnostic. Point it at any Python project with
`--project-root` (default: auto-detected by walking up from the current
directory looking for pyproject.toml / setup.py / setup.cfg / .git) and
it auto-detects sensible defaults: source/test directories, the
dependency-install command, which linters/type-checkers are configured,
and which pre-commit hooks exist. Every auto-detected default can be
overridden with a JSON config file (see `--config` and CONFIG SCHEMA
below), so the same script file works unmodified across many repos.

It is also read-only with respect to source code by default: every check
that invokes pre-commit (which can autofix/modify files) runs inside a
`git stash` guard that pushes any uncommitted changes out of the way
first and pops them back afterwards, discarding only the mutations that
check itself introduced -- so a discovery run never leaves behind
modified files, and never destroys pre-existing uncommitted work in the
target repo either. Pass `--apply-fixes` to disable the guard and let
autofixers mutate the real working tree instead.

Usage:
    python ci_discovery.py [--project-root PATH] [--config PATH]
                            [--output PATH] [--apply-fixes]
                            [--skip ID[,ID...]] [--only ID[,ID...]]
                            [--supplemental-findings PATH] [--list-checks]

Exit code is always 0 (fail-open) unless the script itself crashes;
inspect the report's "summary.blocking_findings" field to know whether
CI-breaking issues were discovered.

CONFIG SCHEMA (all keys optional; JSON file passed via --config):
    {
      "repo_name": "my-service",
      "install_cmd": ["python", "-m", "pip", "install", "--dry-run",
                       "--ignore-installed", "-e", ".[dev]"],
      "lint_paths": ["src", "tests"],
      "typecheck_paths": ["src"],
      "run_mypy": true,
      "autofix_hook_ids": ["end-of-file-fixer", "ruff", "ruff-format", "black"],
      "tool_version_map": {"astral-sh/ruff-pre-commit": "ruff"},
      "extra_checks": [
        {
          "id": "predeploy-check",
          "description": "scripts/predeploy_check.py must pass before deploy",
          "command": ["python", "scripts/predeploy_check.py"],
          "cwd": ".",
          "category": "deploy-script"
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - py<3.11 fallback
    tomllib = None  # type: ignore[assignment]

DEFAULT_TOOL_VERSION_MAP: dict[str, str] = {
    "astral-sh/ruff-pre-commit": "ruff",
    "pre-commit/mirrors-mypy": "mypy",
    "psf/black": "black",
    "pycqa/isort": "isort",
    "pycqa/flake8": "flake8",
}

#: Hooks that are pure formatters/fixers and must fully converge to zero
#: findings after one autofix pass. Deliberately excludes linter hooks like
#: "ruff" (as opposed to "ruff-format") that autofix *some* violations via
#: `args: [--fix]` but can legitimately still report genuine, non-fixable
#: violations (e.g. unused variables) after fixing -- that's correct
#: behavior, not a convergence failure.
DEFAULT_AUTOFIX_HOOK_IDS: set[str] = {
    "end-of-file-fixer",
    "trailing-whitespace",
    "mixed-line-ending",
    "ruff-format",
    "black",
    "isort",
    "autoflake",
    "pyupgrade",
    "prettier",
}

#: Additional hook ids to exclude from the "non-autofixable findings" pass
#: even though they aren't pure formatters -- their output is redundant
#: with a dedicated CLI-based check elsewhere in the report (ruff-check).
REDUNDANT_WITH_DEDICATED_CHECK_HOOK_IDS: set[str] = {"ruff"}

PIP_RESOLUTION_FAILURE_PATTERNS = [
    re.compile(r"Could not find a version that satisfies the requirement (\S+)"),
    re.compile(r"No matching distribution found for (\S+)"),
    re.compile(r"ResolutionImpossible"),
]

IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
}


# --------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------


@dataclass
class CheckResult:
    id: str
    tool: str
    category: str
    command: str
    status: str  # "pass" | "fail" | "error" | "skipped"
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    blocking: bool
    exit_code: int | None
    summary: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_output_excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "category": self.category,
            "command": self.command,
            "status": self.status,
            "severity": self.severity,
            "blocking": self.blocking,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "error_count": len(self.errors),
            "errors": self.errors,
            "notes": self.notes,
            "raw_output_excerpt": self.raw_output_excerpt,
        }


def skipped(check_id: str, tool: str, category: str, reason: str) -> CheckResult:
    return CheckResult(
        id=check_id,
        tool=tool,
        category=category,
        command="",
        status="skipped",
        severity="info",
        blocking=False,
        exit_code=None,
        summary=reason,
    )


# --------------------------------------------------------------------------
# Process execution
# --------------------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> tuple[int, str, str]:
    """Run a subprocess in fail-open mode: never raise on non-zero exit."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, stdout, f"{stderr}\n[ci_discovery] TIMEOUT after {timeout}s"
    except FileNotFoundError as exc:
        return 127, "", f"[ci_discovery] executable not found: {exc}"


def excerpt(text: str, limit: int = 4000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def extract_version(text: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+){1,3}", text)
    return match.group(0) if match else None


# --------------------------------------------------------------------------
# Working-tree safety guard
# --------------------------------------------------------------------------


@contextmanager
def git_change_guard(git_root: Path, is_git_repo: bool, apply_fixes: bool) -> Iterator[None]:
    """
    Make the wrapped block's filesystem mutations disposable.

    Stashes ALL current uncommitted changes (tracked + untracked) before
    entering, so the wrapped block starts from a clean HEAD state; on exit,
    discards whatever the wrapped block itself changed (checkout + clean)
    and pops the original stash back, restoring exactly what was there
    before this guard ran -- including changes unrelated to this tool.

    A no-op if apply_fixes is set or this isn't a git repository.
    """
    if apply_fixes or not is_git_repo:
        yield
        return

    stash_cmd = ["git", "stash", "push", "-u", "-m", "ci-discovery-guard"]
    code, out, _ = run(stash_cmd, cwd=git_root)
    stash_created = code == 0 and "No local changes to save" not in out
    try:
        yield
    finally:
        run(["git", "checkout", "--", "."], cwd=git_root)
        run(["git", "clean", "-fd"], cwd=git_root)
        if stash_created:
            run(["git", "stash", "pop"], cwd=git_root)


# --------------------------------------------------------------------------
# Repo auto-detection
# --------------------------------------------------------------------------


def discover_project_root(start: Path) -> Path:
    markers = ("pyproject.toml", "setup.py", "setup.cfg")
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def discover_git_root(project_root: Path) -> tuple[Path, bool]:
    code, out, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=project_root, timeout=10)
    if code == 0 and out.strip():
        return Path(out.strip()), True
    return project_root, False


def load_pyproject(project_root: Path) -> dict[str, Any] | None:
    path = project_root / "pyproject.toml"
    if not path.exists() or tomllib is None:
        return None
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return None


def load_json_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"config/findings file not found: {path}")
    return json.loads(path.read_text())


def has_py_files(directory: Path) -> bool:
    try:
        next(directory.rglob("*.py"))
        return True
    except StopIteration:
        return False


def autodetect_lint_paths(project_root: Path, pyproject: dict[str, Any] | None) -> list[str]:
    if pyproject:
        ruff_src = pyproject.get("tool", {}).get("ruff", {}).get("src")
        if ruff_src:
            return list(ruff_src)

    candidates: list[str] = []
    for name in ("src", "app", "lib"):
        if (project_root / name).is_dir():
            candidates.append(name)

    if not candidates:
        for child in sorted(project_root.iterdir()):
            if (
                child.is_dir()
                and child.name not in IGNORED_DIR_NAMES
                and not child.name.startswith(".")
                and child.name != "tests"
                and has_py_files(child)
            ):
                candidates.append(child.name)

    if not candidates:
        candidates = ["."]

    if (project_root / "tests").is_dir():
        candidates.append("tests")

    return candidates


def autodetect_typecheck_paths(lint_paths: list[str]) -> list[str]:
    non_test = [p for p in lint_paths if p != "tests"]
    return non_test or lint_paths


def has_mypy_config(project_root: Path, pyproject: dict[str, Any] | None) -> bool:
    if pyproject and "mypy" in pyproject.get("tool", {}):
        return True
    return (project_root / "mypy.ini").exists() or (project_root / ".mypy.ini").exists()


def has_pytest_config(project_root: Path, pyproject: dict[str, Any] | None) -> bool:
    if pyproject and "pytest" in pyproject.get("tool", {}).get("ini_options", {}):
        return True
    if pyproject and "pytest" in pyproject.get("tool", {}):
        return True
    return (project_root / "pytest.ini").exists() or (project_root / "tests").is_dir()


def autodetect_install_cmd(project_root: Path, pyproject: dict[str, Any] | None) -> list[str]:
    if pyproject and "project" in pyproject:
        optional = pyproject["project"].get("optional-dependencies", {})
        extra = "dev" if "dev" in optional else (next(iter(optional), None) if optional else None)
        target = f".[{extra}]" if extra else "."
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "-e",
            target,
        ]
    for req_name in ("requirements-dev.txt", "requirements.txt"):
        if (project_root / req_name).exists():
            return [sys.executable, "-m", "pip", "install", "--dry-run", "-r", req_name]
    return []


@dataclass
class RepoContext:
    project_root: Path
    git_root: Path
    is_git_repo: bool
    repo_name: str
    pyproject: dict[str, Any] | None
    precommit_config_path: Path | None
    precommit_text: str | None
    lint_paths: list[str]
    typecheck_paths: list[str]
    install_cmd: list[str]
    run_mypy: bool
    run_pytest: bool
    autofix_hook_ids: set[str]
    tool_version_map: dict[str, str]
    extra_checks: list[dict[str, Any]]


def build_context(project_root: Path, user_config: dict[str, Any]) -> RepoContext:
    git_root, is_git = discover_git_root(project_root)
    pyproject = load_pyproject(project_root)

    precommit_path = project_root / ".pre-commit-config.yaml"
    if not precommit_path.exists():
        precommit_path = project_root / ".pre-commit-config.yml"
    precommit_text = precommit_path.read_text() if precommit_path.exists() else None
    if precommit_text is None:
        precommit_path = None

    repo_name = (
        user_config.get("repo_name")
        or (pyproject.get("project", {}).get("name") if pyproject else None)
        or project_root.name
    )

    lint_paths = user_config.get("lint_paths") or autodetect_lint_paths(project_root, pyproject)
    typecheck_paths = user_config.get("typecheck_paths") or autodetect_typecheck_paths(lint_paths)
    install_cmd = user_config.get("install_cmd") or autodetect_install_cmd(project_root, pyproject)

    run_mypy = user_config.get("run_mypy")
    if run_mypy is None:
        run_mypy = shutil.which("mypy") is not None and has_mypy_config(project_root, pyproject)

    run_pytest = user_config.get("run_pytest")
    if run_pytest is None:
        run_pytest = shutil.which("pytest") is not None and has_pytest_config(
            project_root, pyproject
        )

    return RepoContext(
        project_root=project_root,
        git_root=git_root,
        is_git_repo=is_git,
        repo_name=repo_name,
        pyproject=pyproject,
        precommit_config_path=precommit_path,
        precommit_text=precommit_text,
        lint_paths=lint_paths,
        typecheck_paths=typecheck_paths,
        install_cmd=install_cmd,
        run_mypy=bool(run_mypy),
        run_pytest=bool(run_pytest),
        autofix_hook_ids=set(user_config.get("autofix_hook_ids") or DEFAULT_AUTOFIX_HOOK_IDS),
        tool_version_map={
            **DEFAULT_TOOL_VERSION_MAP,
            **(user_config.get("tool_version_map") or {}),
        },
        extra_checks=user_config.get("extra_checks") or [],
    )


# --------------------------------------------------------------------------
# .pre-commit-config.yaml line-scan helpers (no PyYAML dependency required)
# --------------------------------------------------------------------------


def find_hooks_with_additional_deps(precommit_text: str) -> list[str]:
    hooks: list[str] = []
    current_id: str | None = None
    has_additional_deps = False

    def flush() -> None:
        if current_id and has_additional_deps:
            hooks.append(current_id)

    for raw_line in precommit_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- id:"):
            flush()
            current_id = stripped.split(":", 1)[1].strip()
            has_additional_deps = False
        elif stripped.startswith("additional_dependencies:") and current_id:
            has_additional_deps = True
    flush()
    return hooks


def find_repo_revs(precommit_text: str) -> list[tuple[str, str]]:
    """
    Parse (repo_url, pinned_rev) pairs out of a .pre-commit-config.yaml.

    Each repo entry is a YAML list item ("- repo: <url>") followed by an
    indented, non-list "rev: <tag>" key -- e.g.:
        repos:
          - repo: https://github.com/astral-sh/ruff-pre-commit
            rev: v0.6.9
            hooks: [...]
    """
    pairs: list[tuple[str, str]] = []
    current_repo: str | None = None
    for raw_line in precommit_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- repo:"):
            current_repo = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("rev:") and current_repo:
            rev = stripped.split(":", 1)[1].strip().lstrip("v").strip("'\"")
            pairs.append((current_repo, rev))
            current_repo = None
    return pairs


HOOK_STATUS_LINE = re.compile(r"\.{3,}\s*(Passed|Failed|Skipped)\s*$")


def parse_precommit_hook_blocks(text: str) -> dict[str, list[str]]:
    """
    Map hook id -> raw detail lines emitted while that hook was reported as
    failing. pre-commit's per-hook failure detail (e.g. check-yaml's
    multi-line "expected a single document..." message) is often separated
    from the "- hook id: X" header by a blank line, so a block only ends
    when the *next* hook's "<name>...Passed/Failed/Skipped" summary line
    (or the next "- hook id:") appears -- not on the first blank line.
    """
    blocks: dict[str, list[str]] = {}
    current_hook: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- hook id:"):
            current_hook = stripped.split(":", 1)[1].strip()
            blocks.setdefault(current_hook, [])
            continue
        if current_hook and HOOK_STATUS_LINE.search(stripped):
            current_hook = None
            continue
        if (
            current_hook
            and stripped
            and not stripped.startswith("- exit code:")
            and not stripped.startswith("- files were modified")
        ):
            blocks[current_hook].append(stripped)
    return blocks


def parse_code_style_findings(lines: list[str]) -> list[dict[str, Any]]:
    """Parse ruff/mypy-style 'path:line:col: message' lines out of a hook's output block."""
    findings = []
    for line in lines:
        parts = line.split(":", 3)
        if len(parts) == 4 and parts[1].strip().isdigit():
            path, lineno, col, rest = parts
            findings.append(
                {
                    "file": path.strip(),
                    "line": int(lineno.strip()),
                    "column": int(col.strip()) if col.strip().isdigit() else None,
                    "message": rest.strip(),
                }
            )
    return findings


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_dependency_install(ctx: RepoContext) -> CheckResult:
    if not ctx.install_cmd:
        return skipped(
            "dependency-install",
            "pip",
            "environment",
            "No pyproject.toml / requirements*.txt found; nothing to install.",
        )

    code, out, err = run(ctx.install_cmd, cwd=ctx.project_root, timeout=120)
    combined = out + "\n" + err
    errors: list[dict[str, Any]] = []
    offending_packages: set[str] = set()
    for line in combined.splitlines():
        if line.startswith("ERROR:"):
            errors.append({"tool": "pip", "message": line.removeprefix("ERROR:").strip()})
        for pattern in PIP_RESOLUTION_FAILURE_PATTERNS:
            match = pattern.search(line)
            if match and match.groups():
                offending_packages.add(match.group(1))

    status = "pass" if code == 0 else "fail"
    summary = "dependency set resolves cleanly."
    if errors:
        pkgs = ", ".join(sorted(offending_packages)) or "one or more packages"
        summary = (
            f"pip cannot resolve {pkgs} from any configured index. Reproduced with "
            f"--ignore-installed so an already-installed local/editable copy doesn't mask "
            f"the failure. This is the exact command a clean CI runner's dependency-install "
            f"step would run, so CI's install step will fail identically."
        )
    return CheckResult(
        id="dependency-install",
        tool="pip",
        category="environment",
        command=" ".join(ctx.install_cmd),
        status=status,
        severity="critical" if errors else "info",
        blocking=bool(errors),
        exit_code=code,
        summary=summary,
        errors=errors,
        raw_output_excerpt=excerpt(combined),
    )


def check_precommit_hook_envs(ctx: RepoContext, apply_fixes: bool) -> list[CheckResult]:
    if ctx.precommit_config_path is None or ctx.precommit_text is None:
        return [
            skipped(
                "pre-commit-hook-envs",
                "pre-commit",
                "environment",
                "No .pre-commit-config.yaml found.",
            )
        ]
    if shutil.which("pre-commit") is None:
        return [
            skipped(
                "pre-commit-hook-envs",
                "pre-commit",
                "environment",
                "pre-commit is not installed in this environment.",
            )
        ]

    hook_ids = find_hooks_with_additional_deps(ctx.precommit_text)
    if not hook_ids:
        return [
            skipped(
                "pre-commit-hook-envs",
                "pre-commit",
                "environment",
                "No hooks declare additional_dependencies; nothing to validate.",
            )
        ]

    results = []
    with git_change_guard(ctx.git_root, ctx.is_git_repo, apply_fixes):
        for hook_id in hook_ids:
            cmd = [
                "pre-commit",
                "run",
                hook_id,
                "--all-files",
                "-c",
                str(ctx.precommit_config_path),
            ]
            code, out, err = run(cmd, cwd=ctx.git_root, timeout=120)
            combined = out + "\n" + err
            blocked = any(pattern.search(combined) for pattern in PIP_RESOLUTION_FAILURE_PATTERNS)
            offending = set()
            for pattern in PIP_RESOLUTION_FAILURE_PATTERNS:
                for match in pattern.finditer(combined):
                    if match.groups():
                        offending.add(match.group(1))

            errors = []
            if blocked:
                pkgs = ", ".join(sorted(offending)) or "one or more additional_dependencies"
                errors.append(
                    {
                        "tool": "pre-commit",
                        "hook": hook_id,
                        "message": f"cannot resolve {pkgs} when building this hook's isolated venv",
                    }
                )
            results.append(
                CheckResult(
                    id=f"pre-commit-hook-env:{hook_id}",
                    tool="pre-commit",
                    category="environment",
                    command=" ".join(cmd),
                    status="fail" if blocked else ("pass" if code == 0 else "error"),
                    severity="critical" if blocked else "info",
                    blocking=blocked,
                    exit_code=code,
                    summary=(
                        f"pre-commit's '{hook_id}' hook environment cannot be built: an "
                        f"additional_dependencies entry cannot be resolved. `pre-commit run` "
                        f"fails on environment setup before this hook ever executes."
                        if blocked
                        else f"'{hook_id}' hook environment built and ran successfully."
                    ),
                    errors=errors,
                    notes=[
                        "pre-commit provisions an isolated venv per hook from "
                        "additional_dependencies, independent of however the main project "
                        "environment installs its own dependencies.",
                    ],
                    raw_output_excerpt=excerpt(combined),
                )
            )
    return results


def check_precommit_autofix(ctx: RepoContext, apply_fixes: bool) -> CheckResult:
    if ctx.precommit_config_path is None:
        return skipped(
            "pre-commit-autofix-validation",
            "pre-commit",
            "tooling-validation",
            "No .pre-commit-config.yaml found.",
        )
    if shutil.which("pre-commit") is None:
        return skipped(
            "pre-commit-autofix-validation",
            "pre-commit",
            "tooling-validation",
            "pre-commit is not installed in this environment.",
        )
    if not ctx.is_git_repo and not apply_fixes:
        return skipped(
            "pre-commit-autofix-validation",
            "pre-commit",
            "tooling-validation",
            "Not inside a git repository; autofix validation requires `git stash`. Pass "
            "--apply-fixes to run it anyway (this will mutate files in place).",
        )

    broken_env_hooks = find_hooks_with_additional_deps(ctx.precommit_text or "")
    skip_ids = ",".join(broken_env_hooks) if broken_env_hooks else ""

    with git_change_guard(ctx.git_root, ctx.is_git_repo, apply_fixes):
        cmd = ["pre-commit", "run", "--all-files", "-c", str(ctx.precommit_config_path)]
        env = {"SKIP": skip_ids} if skip_ids else None
        code1, out1, err1 = run(cmd, cwd=ctx.git_root, env=env, timeout=180)
        diff_code, diff_out, _ = run(["git", "diff", "--stat"], cwd=ctx.git_root, timeout=60)
        code2, out2, err2 = run(cmd, cwd=ctx.git_root, env=env, timeout=180)

    first_pass = out1 + "\n" + err1
    second_pass = out2 + "\n" + err2

    second_pass_blocks = parse_precommit_hook_blocks(second_pass)
    remaining_errors: list[dict[str, Any]] = []
    for hook_id, lines in second_pass_blocks.items():
        findings = parse_code_style_findings(lines)
        if findings:
            for finding in findings:
                remaining_errors.append({"hook": hook_id, **finding})
        elif lines:
            remaining_errors.append({"hook": hook_id, "message": " ".join(lines)[:500]})

    still_autofixable = any(e.get("hook") in ctx.autofix_hook_ids for e in remaining_errors)
    autofix_validated = code2 == 0 or not still_autofixable

    files_modified = diff_out.strip().splitlines()[-1] if diff_out.strip() else "0 files changed"

    return CheckResult(
        id="pre-commit-autofix-validation",
        tool="pre-commit",
        category="tooling-validation",
        command=" ".join(cmd) + (f"  (run twice, SKIP={skip_ids})" if skip_ids else " (run twice)"),
        status="pass" if autofix_validated else "fail",
        severity="info" if autofix_validated else "medium",
        blocking=False,
        exit_code=code2,
        summary=(
            f"Autofix-capable hooks converge: first pass modified files ({files_modified}), "
            f"second pass on the fixed tree only surfaces non-autofixable findings "
            f"({len(remaining_errors)} remaining)."
            if autofix_validated
            else "Autofix hooks did not converge; a second pass still reports autofixable "
            "findings, which should not happen."
        ),
        errors=remaining_errors,
        notes=[
            f"Hooks skipped here (isolated env can't be validated by a text diff): {skip_ids}"
            if skip_ids
            else "No hooks were skipped for this pass.",
            f"git diff --stat after first pass: {files_modified}",
            "Working tree changes made by this validation pass are reverted via `git stash` "
            "unless --apply-fixes is supplied.",
        ],
        raw_output_excerpt=excerpt(first_pass),
    )


def check_precommit_non_autofixable(ctx: RepoContext, apply_fixes: bool) -> CheckResult:
    if ctx.precommit_config_path is None:
        return skipped(
            "pre-commit-non-autofixable-findings",
            "pre-commit",
            "lint",
            "No .pre-commit-config.yaml found.",
        )
    if shutil.which("pre-commit") is None:
        return skipped(
            "pre-commit-non-autofixable-findings",
            "pre-commit",
            "lint",
            "pre-commit is not installed in this environment.",
        )

    broken_env_hooks = find_hooks_with_additional_deps(ctx.precommit_text or "")
    skip_ids = (
        ctx.autofix_hook_ids | REDUNDANT_WITH_DEDICATED_CHECK_HOOK_IDS | set(broken_env_hooks)
    )
    cmd = ["pre-commit", "run", "--all-files", "-c", str(ctx.precommit_config_path)]

    with git_change_guard(ctx.git_root, ctx.is_git_repo, apply_fixes):
        code, out, err = run(cmd, cwd=ctx.git_root, env={"SKIP": ",".join(skip_ids)}, timeout=120)

    combined = out + "\n" + err
    blocks = parse_precommit_hook_blocks(combined)
    errors: list[dict[str, Any]] = []
    for hook_id, lines in blocks.items():
        findings = parse_code_style_findings(lines)
        if findings:
            for finding in findings:
                errors.append({"hook": hook_id, **finding})
        elif lines:
            errors.append({"hook": hook_id, "message": " ".join(lines)[:500]})

    return CheckResult(
        id="pre-commit-non-autofixable-findings",
        tool="pre-commit",
        category="lint",
        command=" ".join(cmd),
        status="pass" if code == 0 else "fail",
        severity="low" if errors else "info",
        blocking=False,
        exit_code=code,
        summary=(
            f"{len(errors)} validator-only pre-commit hook finding(s) with no autofix available."
            if errors
            else "All validator-only hooks passed."
        ),
        errors=errors,
        raw_output_excerpt=excerpt(combined),
    )


def check_ruff(ctx: RepoContext) -> CheckResult:
    if shutil.which("ruff") is None:
        return skipped("ruff-check", "ruff", "lint", "ruff is not installed in this environment.")

    cmd = ["ruff", "check", "--output-format=json", *ctx.lint_paths]
    code, out, err = run(cmd, cwd=ctx.project_root, timeout=60)
    try:
        violations = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        violations = []
    errors = []
    fixable = 0
    for violation in violations:
        is_fixable = bool(violation.get("fix"))
        fixable += int(is_fixable)
        errors.append(
            {
                "file": os.path.relpath(violation["filename"], ctx.project_root),
                "line": violation["location"]["row"],
                "column": violation["location"]["column"],
                "code": violation["code"],
                "message": violation["message"],
                "fixable": is_fixable,
                "url": violation.get("url"),
            }
        )
    return CheckResult(
        id="ruff-check",
        tool="ruff",
        category="lint",
        command=" ".join(cmd),
        status="pass" if code == 0 else "fail",
        severity="medium" if errors else "info",
        blocking=False,
        exit_code=code,
        summary=(
            f"{len(errors)} ruff lint violation(s) across {', '.join(ctx.lint_paths)} "
            f"({fixable} auto-fixable with `ruff check --fix`)."
            if errors
            else "No ruff lint violations."
        ),
        errors=errors,
        raw_output_excerpt=excerpt(err or out),
    )


def check_ruff_format(ctx: RepoContext) -> CheckResult:
    if shutil.which("ruff") is None:
        return skipped(
            "ruff-format-check", "ruff", "formatting", "ruff is not installed in this environment."
        )

    cmd = ["ruff", "format", "--check", *ctx.lint_paths]
    code, out, err = run(cmd, cwd=ctx.project_root, timeout=60)
    combined = out + "\n" + err
    files = [
        line.strip().removeprefix("Would reformat:").strip()
        for line in combined.splitlines()
        if line.strip().startswith("Would reformat:")
    ]
    errors = [{"file": f, "message": "would be reformatted by `ruff format`"} for f in files]
    return CheckResult(
        id="ruff-format-check",
        tool="ruff",
        category="formatting",
        command=" ".join(cmd),
        status="pass" if code == 0 else "fail",
        severity="low" if errors else "info",
        blocking=False,
        exit_code=code,
        summary=(
            f"{len(errors)} file(s) not formatted per `ruff format` (all auto-fixable)."
            if errors
            else "All files already match ruff-format output."
        ),
        errors=errors,
        raw_output_excerpt=excerpt(combined),
    )


def check_mypy(ctx: RepoContext) -> CheckResult:
    if not ctx.run_mypy:
        reason = (
            "mypy is not installed in this environment."
            if shutil.which("mypy") is None
            else "No mypy configuration found (pyproject [tool.mypy] / mypy.ini); "
            "set run_mypy=true in --config to force."
        )
        return skipped("mypy-check", "mypy", "type-check", reason)

    cmd = ["mypy", "-O", "json", "--no-error-summary", *ctx.typecheck_paths]
    code, out, err = run(cmd, cwd=ctx.project_root, timeout=120)
    errors = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("severity") != "error":
            continue
        errors.append(
            {
                "file": payload.get("file"),
                "line": payload.get("line"),
                "column": payload.get("column"),
                "code": payload.get("code"),
                "message": payload.get("message"),
                "hint": payload.get("hint"),
            }
        )
    return CheckResult(
        id="mypy-check",
        tool="mypy",
        category="type-check",
        command=" ".join(cmd),
        status="pass" if code == 0 else "fail",
        severity="high" if errors else "info",
        blocking=False,
        exit_code=code,
        summary=(
            f"{len(errors)} mypy error(s) across {', '.join(ctx.typecheck_paths)}."
            if errors
            else "No mypy errors."
        ),
        errors=errors,
        raw_output_excerpt=excerpt(err or out),
    )


def check_pytest_collection(ctx: RepoContext) -> CheckResult:
    if not ctx.run_pytest:
        reason = (
            "pytest is not installed in this environment."
            if shutil.which("pytest") is None
            else "No tests directory or pytest configuration found; set run_pytest=true in "
            "--config to force."
        )
        return skipped("pytest-collection", "pytest", "test", reason)

    cmd = ["pytest", "--collect-only", "-q"]
    code, out, err = run(cmd, cwd=ctx.project_root, timeout=60)
    combined = out + "\n" + err

    failing_module = None
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped.startswith(("ImportError while", "ERROR collecting", "ERROR ")):
            match = re.search(r"[\w./\\-]+\.py", stripped)
            if match:
                failing_module = match.group(0)

    errors: list[dict[str, Any]] = []
    import_error_msg = None
    chain: list[str] = []
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped.startswith("E   "):
            import_error_msg = stripped.removeprefix("E   ").strip()
        elif ".py:" in stripped and " in " in stripped:
            chain.append(stripped)

    if import_error_msg:
        errors.append(
            {
                "file": failing_module,
                "message": import_error_msg,
                "import_chain": chain,
                "severity": "critical",
            }
        )

    blocking = bool(errors) or code != 0
    return CheckResult(
        id="pytest-collection",
        tool="pytest",
        category="test",
        command=" ".join(cmd),
        status="fail" if blocking else "pass",
        severity="critical" if errors else ("high" if blocking else "info"),
        blocking=blocking,
        exit_code=code,
        summary=(
            f"Collection fails while importing {failing_module or 'a test module'}, which can "
            "block collection of dependent tests -- the same failure a CI `pytest` step would "
            "hit."
            if errors
            else (
                "pytest failed to collect for a reason other than an import error."
                if blocking
                else "All tests collected successfully with no import errors."
            )
        ),
        errors=errors,
        notes=[
            "This deliberately runs --collect-only and never executes tests: getting past a "
            "collection-time ImportError requires source changes, which is out of scope for a "
            "read-only discovery tool. Use --supplemental-findings to attach a manually "
            "produced deeper scan once such a blocker is fixed or worked around locally.",
        ],
        raw_output_excerpt=excerpt(combined),
    )


def check_version_drift(ctx: RepoContext) -> CheckResult:
    if not ctx.precommit_text:
        return skipped(
            "tooling-version-drift", "meta", "environment", "No .pre-commit-config.yaml found."
        )

    repo_revs = find_repo_revs(ctx.precommit_text)
    drift = []
    checked_any = False
    for repo_url, pinned_rev in repo_revs:
        tool_name = next(
            (tool for key, tool in ctx.tool_version_map.items() if key in repo_url), None
        )
        if not tool_name or shutil.which(tool_name) is None:
            continue
        checked_any = True
        _, version_out, _ = run([tool_name, "--version"], cwd=ctx.project_root, timeout=15)
        resolved_version = extract_version(version_out)
        if resolved_version and resolved_version != pinned_rev:
            drift.append(
                {
                    "tool": tool_name,
                    "pre_commit_pinned_rev": pinned_rev,
                    "resolved_version": resolved_version,
                    "message": (
                        f"pre-commit pins {tool_name}=={pinned_rev} but the version resolved "
                        f"in this environment is {resolved_version}; local/CI runs invoking "
                        f"`{tool_name}` directly and the pinned pre-commit hook can disagree."
                    ),
                }
            )

    if not checked_any:
        return skipped(
            "tooling-version-drift",
            "meta",
            "environment",
            "No pinned pre-commit repos matched a known tool_version_map entry with an "
            "installed CLI; nothing to compare.",
        )

    return CheckResult(
        id="tooling-version-drift",
        tool="meta",
        category="environment",
        command="static comparison of .pre-commit-config.yaml pins vs resolved CLI versions",
        status="fail" if drift else "pass",
        severity="medium" if drift else "info",
        blocking=False,
        exit_code=0,
        summary=(
            f"{len(drift)} tool(s) have version drift between their pre-commit pin and the "
            "version resolved in this environment."
            if drift
            else "No version drift detected between pre-commit pins and resolved versions."
        ),
        errors=drift,
    )


def check_extra(ctx: RepoContext, spec: dict[str, Any], apply_fixes: bool) -> CheckResult:
    check_id = f"extra:{spec.get('id') or 'unnamed'}"
    command = spec.get("command")
    if not command:
        return skipped(check_id, "custom", spec.get("category", "custom"), "no command configured")

    cwd = ctx.project_root / spec.get("cwd", ".")
    with git_change_guard(ctx.git_root, ctx.is_git_repo, apply_fixes):
        code, out, err = run(command, cwd=cwd, timeout=spec.get("timeout", 60))

    combined = out + "\n" + err
    errors = [
        {"message": line.removeprefix("ERROR:").strip()}
        for line in combined.splitlines()
        if line.strip().startswith("ERROR:")
    ] or ([{"message": combined.strip()[-500:]}] if code != 0 else [])

    return CheckResult(
        id=check_id,
        tool="custom",
        category=spec.get("category", "custom"),
        command=" ".join(command),
        status="pass" if code == 0 else "fail",
        severity=spec.get("severity", "medium") if code != 0 else "info",
        blocking=bool(spec.get("blocking", False)) and code != 0,
        exit_code=code,
        summary=spec.get("description", f"custom check '{check_id}'")
        + (" -- FAILED" if code != 0 else " -- passed"),
        errors=errors,
        raw_output_excerpt=excerpt(combined),
    )


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def should_run(check_id: str, skip_prefixes: list[str], only_prefixes: list[str] | None) -> bool:
    if only_prefixes and not any(check_id.startswith(p) for p in only_prefixes):
        return False
    if any(check_id.startswith(p) for p in skip_prefixes):
        return False
    return True


def build_report(
    ctx: RepoContext,
    *,
    apply_fixes: bool,
    skip_prefixes: list[str],
    only_prefixes: list[str] | None,
    supplemental_findings: dict[str, Any] | None,
) -> dict[str, Any]:
    results: list[CheckResult] = []

    def add(result: CheckResult | list[CheckResult]) -> None:
        items = result if isinstance(result, list) else [result]
        for item in items:
            if should_run(item.id, skip_prefixes, only_prefixes):
                results.append(item)

    add(check_dependency_install(ctx))
    add(check_precommit_hook_envs(ctx, apply_fixes))
    add(check_precommit_autofix(ctx, apply_fixes))
    add(check_precommit_non_autofixable(ctx, apply_fixes))
    add(check_ruff(ctx))
    add(check_ruff_format(ctx))
    add(check_mypy(ctx))
    add(check_pytest_collection(ctx))
    add(check_version_drift(ctx))
    for spec in ctx.extra_checks:
        add(check_extra(ctx, spec, apply_fixes))

    git_sha_code, git_sha_out, _ = run(["git", "rev-parse", "HEAD"], cwd=ctx.git_root, timeout=10)
    git_branch_code, git_branch_out, _ = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ctx.git_root, timeout=10
    )

    total_errors = sum(len(r.errors) for r in results)
    blocking = [r.id for r in results if r.blocking]

    report: dict[str, Any] = {
        "$schema": "https://internal/schemas/ci-discovery-report-v1.json",
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": ctx.repo_name,
        "project_root": str(ctx.project_root),
        "git_commit": git_sha_out.strip() if git_sha_code == 0 else None,
        "git_branch": git_branch_out.strip() if git_branch_code == 0 else None,
        "mode": "fail-open-discovery",
        "detected_config": {
            "lint_paths": ctx.lint_paths,
            "typecheck_paths": ctx.typecheck_paths,
            "install_cmd": ctx.install_cmd,
            "run_mypy": ctx.run_mypy,
            "run_pytest": ctx.run_pytest,
            "has_precommit_config": ctx.precommit_config_path is not None,
        },
        "summary": {
            "checks_run": len(results),
            "checks_failed": sum(1 for r in results if r.status == "fail"),
            "checks_passed": sum(1 for r in results if r.status == "pass"),
            "checks_skipped": sum(1 for r in results if r.status == "skipped"),
            "total_findings": total_errors,
            "blocking_findings": len(blocking),
            "blocking_check_ids": blocking,
        },
        "checks": [r.to_dict() for r in results],
    }
    if supplemental_findings:
        report["supplemental_manual_findings"] = supplemental_findings
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

ALL_CHECK_IDS = [
    "dependency-install",
    "pre-commit-hook-env:<hook-id>",
    "pre-commit-autofix-validation",
    "pre-commit-non-autofixable-findings",
    "ruff-check",
    "ruff-format-check",
    "mypy-check",
    "pytest-collection",
    "tooling-version-drift",
    "extra:<configured-id>",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Directory containing pyproject.toml/.pre-commit-config.yaml for the target "
        "project. Defaults to auto-detecting by walking up from the current directory.",
    )
    parser.add_argument("--config", default=None, help="Path to a JSON config override file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write the JSON report to. Defaults to "
        "<project-root>/reports/ci_discovery_report.json.",
    )
    parser.add_argument(
        "--apply-fixes",
        action="store_true",
        help="Let autofix-capable hooks mutate the real working tree instead of reverting "
        "them after validation.",
    )
    parser.add_argument("--skip", default=None, help="Comma-separated check id prefixes to skip.")
    parser.add_argument(
        "--only", default=None, help="Comma-separated check id prefixes to run exclusively."
    )
    parser.add_argument(
        "--supplemental-findings",
        default=None,
        help="Path to a JSON file merged verbatim into the report's "
        "'supplemental_manual_findings' key (e.g. notes from a manual deep-scan).",
    )
    parser.add_argument(
        "--list-checks", action="store_true", help="Print available check ids and exit."
    )
    args = parser.parse_args()

    if args.list_checks:
        print("\n".join(ALL_CHECK_IDS))
        return 0

    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else discover_project_root(Path.cwd())
    )
    user_config = load_json_file(Path(args.config) if args.config else None)
    ctx = build_context(project_root, user_config)
    supplemental_findings = (
        load_json_file(Path(args.supplemental_findings) if args.supplemental_findings else None)
        or None
    )

    skip_prefixes = args.skip.split(",") if args.skip else []
    only_prefixes = args.only.split(",") if args.only else None

    report = build_report(
        ctx,
        apply_fixes=args.apply_fixes,
        skip_prefixes=skip_prefixes,
        only_prefixes=only_prefixes,
        supplemental_findings=supplemental_findings,
    )

    output_path = (
        Path(args.output) if args.output else project_root / "reports" / "ci_discovery_report.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")

    print(f"[ci_discovery] project_root={project_root}")
    print(f"[ci_discovery] wrote report to {output_path}")
    print(
        f"[ci_discovery] checks_run={report['summary']['checks_run']} "
        f"failed={report['summary']['checks_failed']} "
        f"skipped={report['summary']['checks_skipped']} "
        f"total_findings={report['summary']['total_findings']} "
        f"blocking={report['summary']['blocking_findings']} "
        f"({', '.join(report['summary']['blocking_check_ids']) or 'none'})"
    )
    return 0  # always fail-open


if __name__ == "__main__":
    raise SystemExit(main())
