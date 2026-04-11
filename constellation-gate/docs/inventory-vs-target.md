# Inventory vs `target-filetree.md`

This document compares **actual files** under `constellation-gate/` to the paths listed in [target-filetree.md](target-filetree.md). Paths are derived by **parsing each tree line’s filename** (the segment after `├──` / `└──`) and **reconstructing the full relative path** using the column position of that connector: `depth = line.find('├──'|'└──') // 4`, then maintaining a path stack. Separator-only lines (`│`) are ignored.

**Counts (approximate; re-run the script below to refresh):** ~109 file paths in the target tree; **3** of those were still missing on disk at last check; **~87** files on disk are **not** listed in the target tree (resilience/runtime/extra tests, CI, extra docs).

---

## Present in target tree but still missing on disk (3)

| Path | Notes |
|------|--------|
| `examples/registry/node_registry.yaml` | No `# filename: examples/registry/...` harvest block located in searched SDK phases. |
| `examples/workflows/full_pipeline.yaml` | Same. |
| `src/constellation_gate/observability/audit_logger.py` | Target lists this; implementation uses `context.py` / `events.py` / etc. instead. |

Many paths that were previously listed here (docs under `docs/`, `contracts/*`, deploy, scripts, config YAMLs, etc.) have since been added or superseded—see git history.

---

## `contracts/` (complete for wire + policy docs)

See **[contracts/README.md](../contracts/README.md)**. Shared SDK files are kept identical to `constellation-node-sdk/contracts/` (sibling package at repo root) via `scripts/sync_contracts_from_sdk.sh`. Gate-only specs: `WORKFLOW_SPEC.md`, `ADMIN_REGISTER_SPEC.md`.

---

## On disk but not in `target-filetree.md` — summary

Real paths under `constellation-gate/` (excluding `__pycache__` / `.pyc`) include **resilience/**, **runtime/**, expanded **tests/**, `.github/`, and docs such as `inventory-vs-target.md` and `target-filetree.md` itself.

---

## Refresh script

```python
# Run from constellation-gate/ with: python3 /path/to/script.py
import re
from pathlib import Path
root = Path(".").resolve()
text = (root / "docs/target-filetree.md").read_text()
lines = text.splitlines()
cut = next((i for i, l in enumerate(lines) if l.strip().startswith("TransportPacket")), len(lines))
lines = lines[:cut]
stack, expected = [], []
for line in lines:
    if "──" not in line:
        continue
    pos = line.find("├──")
    if pos < 0:
        pos = line.find("└──")
    if pos < 0:
        continue
    depth = pos // 4
    rest = line[pos + 4 :].strip()
    if rest in ("│",) or not rest:
        continue
    is_dir = rest.endswith("/")
    name = rest.rstrip("/").strip()
    stack = stack[:depth]
    stack.append(name)
    if not is_dir:
        expected.append("/".join(stack))
present = {
    p.relative_to(root).as_posix()
    for p in root.rglob("*")
    if p.is_file() and "__pycache__" not in str(p) and not str(p).endswith(".pyc")
}
print("missing:", sorted(set(expected) - present))
print("extra count:", len(present - set(expected)))
```

---

## Filename search (examples)

`rg -l 'gate-kernel\\.md|WORKFLOW_SPEC|middleware\\.py|command_factory|audit_logger' --glob '*.md' Gate/`

Phase documents often list names in narrative trees without `# filename:` blocks; those are not automatically harvestable.
