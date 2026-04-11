from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

REQUIRED_ENV = [
    "GATE_LOCAL_NODE",
]

REQUIRED_FILES = [
    "pyproject.toml",
    "src/constellation_gate/api/main.py",
    "src/constellation_gate/config/node_registry.yaml",
    "src/constellation_gate/config/priorities.yaml",
    "src/constellation_gate/config/workflows.yaml",
]


def validate_env() -> list[str]:
    problems: list[str] = []
    for name in REQUIRED_ENV:
        if not os.getenv(name):
            problems.append(f"missing env var: {name}")
    return problems


def validate_files() -> list[str]:
    problems: list[str] = []
    for file_name in REQUIRED_FILES:
        if not Path(file_name).exists():
            problems.append(f"missing required file: {file_name}")
    return problems


def validate_imports() -> list[str]:
    problems: list[str] = []
    for module_name in [
        "constellation_gate.api.main",
        "constellation_gate.services.execute_service",
        "constellation_gate.routing.dispatch",
    ]:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"failed to import {module_name}: {exc}")
    return problems


def main() -> None:
    problems = [
        *validate_env(),
        *validate_files(),
        *validate_imports(),
    ]

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)

    print("predeploy check passed")


if __name__ == "__main__":
    main()
