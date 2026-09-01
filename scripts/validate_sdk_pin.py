#!/usr/bin/env python3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PIN = "d09fe58a6cd68ef8aa883896c68badc95f96e090"
text = (ROOT / "constellation-gate/pyproject.toml").read_text()
errors = []
if f"Quantum-L9/Gate_SDK.git@{PIN}" not in text:
    errors.append("pyproject missing immutable pin")
if "Gate_SDK.git@main" in text:
    errors.append("still floats on main")
if errors:
    print("FAIL"); print("\n".join(errors)); raise SystemExit(1)
print("PASS: Gate SDK pin", PIN)
