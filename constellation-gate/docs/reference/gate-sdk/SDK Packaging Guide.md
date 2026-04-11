SDK Packaging + Installation Execution Guide
1. Final repo shape required
Your SDK repo should look like this at minimum:

constellation-node-sdk/
├── pyproject.toml
├── README.md
├── src/
│   └── constellation_node_sdk/
│       ├── __init__.py
│       ├── py.typed
│       ├── transport/
│       ├── security/
│       ├── gate/
│       ├── runtime/
│       └── orchestrator/
├── tests/
├── contracts/
└── scripts/
The important packaging pieces are:

pyproject.toml

src/constellation_node_sdk/__init__.py

src/constellation_node_sdk/py.typed

2. Your package model
This repo is using the correct modern pattern:

Build backend
setuptools.build_meta

Package layout
src/ layout

Install target
Python package name:

constellation-node-sdk
Import name:

import constellation_node_sdk
That distinction is correct and standard.

3. Minimal packaging commands
Local editable install
For active development:

python -m pip install -e .
Local editable install with dev tools
python -m pip install -e ".[dev]"
Build wheel + sdist
python -m build
This should produce:

dist/
├── constellation_node_sdk-1.0.0-py3-none-any.whl
└── constellation_node_sdk-1.0.0.tar.gz
4. Validate package before publishing
Run this exact sequence:

python -m pip install --upgrade pip setuptools wheel build
python -m pip install -e ".[dev]"
python scripts/validate_contracts.py
python scripts/generate_schema.py
ruff check src tests scripts
mypy src
pytest -q
python -m build
If all of that passes, the SDK is package-ready.

5. Verify wheel contents
After build:

python -m zipfile -l dist/constellation_node_sdk-1.0.0-py3-none-any.whl
You should see:

constellation_node_sdk/__init__.py

transport/security/gate/runtime/orchestrator modules

constellation_node_sdk/py.typed

If py.typed is missing, type consumers will not get proper typed-package behavior.

6. Test install from built wheel
Do not trust only editable mode. Test the actual wheel:

python -m venv .venv-test
source .venv-test/bin/activate
python -m pip install --upgrade pip
python -m pip install dist/constellation_node_sdk-1.0.0-py3-none-any.whl
python -c "import constellation_node_sdk; print('ok')"
Then test a few imports:

python - <<'PY'
from constellation_node_sdk import TransportPacket, create_node_app, GateClient
print("imports ok")
PY
That confirms the install artifact, not just the source tree.

7. Recommended versioning workflow
Use semantic versioning.

Suggested approach:

1.0.0 — first stable internal release

1.0.1 — bugfix only

1.1.0 — backward-compatible features

2.0.0 — protocol-breaking changes

For this repo, treat any of these as potentially breaking:

TransportPacket field changes

hash-domain changes

provenance semantics changes

hop-chain changes

Gate client routing rules

Those should generally trigger a major version bump.

8. Internal release flow
If this is an internal/private library, the clean release process is:

Step A
Tag a version in git:

git tag v1.0.0
git push origin v1.0.0
Step B
Build artifacts:

python -m build
Step C
Publish to your private package index, or attach wheel/tarball to release artifacts.

If you are not using a package registry yet, you can still distribute the wheel directly.

Install from wheel:

python -m pip install /path/to/constellation_node_sdk-1.0.0-py3-none-any.whl
9. If you want PyPI or private registry publishing
PyPI-style publish
Install Twine:

python -m pip install twine
Check artifacts:

python -m twine check dist/*
Upload:

python -m twine upload dist/*
For a private registry, the same flow applies, just with your internal repository URL.

10. How downstream nodes should consume it
A node repo should depend on the SDK in one of these ways.

During development
dependencies = [
  "constellation-node-sdk @ file:///absolute/path/to/dist/constellation_node_sdk-1.0.0-py3-none-any.whl"
]
From private registry
dependencies = [
  "constellation-node-sdk==1.0.0"
]
Then node code should look like:

from constellation_node_sdk import create_node_app, register_handler
and never copy protocol code locally.

11. Recommended release checklist
Before cutting a release:

[ ] pyproject.toml version updated
[ ] README reflects current public API
[ ] contracts validated
[ ] schema normalized
[ ] tests passing
[ ] wheel builds successfully
[ ] wheel installs successfully in clean venv
[ ] key imports work from installed wheel
[ ] examples still reflect real architecture
12. Common failure modes
Missing py.typed
Effect: typed consumers lose type info.

Using source tree only, never testing built wheel
Effect: package looks fine locally but breaks after distribution.

Public API drift in __init__.py
Effect: downstream imports break even though internal modules still exist.

Contract drift between schema and code
Effect: nodes serialize one thing, validators expect another.

Shipping example packets as “real” packets
Effect: consumers may think static JSON examples are meant for runtime use.
Keep examples clearly labeled illustrative.

13. Recommended install commands for your SDK users
For consumers, the shortest guide is:

install
python -m pip install constellation-node-sdk
or internal wheel
python -m pip install constellation_node_sdk-1.0.0-py3-none-any.whl
verify
python - <<'PY'
from constellation_node_sdk import TransportPacket, GateClient, create_node_app
print("sdk ready")
PY
14. Practical conclusion
So yes, your SDK can be packaged as an installable library now.

The execution sequence is:

python -m pip install --upgrade pip setuptools wheel build
python -m pip install -e ".[dev]"
python scripts/validate_contracts.py
python scripts/generate_schema.py
ruff check src tests scripts
mypy src
pytest -q
python -m build
python -m pip install dist/*.whl
That is the clean path from repo to installable SDK artifact.