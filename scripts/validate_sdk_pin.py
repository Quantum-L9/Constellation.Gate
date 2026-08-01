#!/usr/bin/env python3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PIN = "a770e8531dc1c59ce01e1dbb0f4162785d9dda89"
text = (ROOT / "constellation-gate/pyproject.toml").read_text()
errors = []
if f"Quantum-L9/Gate_SDK.git@{PIN}" not in text:
    errors.append("pyproject missing immutable pin")
if "Gate_SDK.git@main" in text:
    errors.append("still floats on main")
if errors:
    print("FAIL"); print("\n".join(errors)); raise SystemExit(1)
print("PASS: Gate SDK pin", PIN)
