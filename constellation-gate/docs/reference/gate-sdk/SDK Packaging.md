
Explain in detail: Build wheel + sdist

When you build wheel + sdist, you are creating the two standard distributable forms of a Python package.

They serve different purposes.

The two artifacts
1. Wheel (.whl)
A wheel is a built distribution.

Example:

dist/constellation_node_sdk-1.0.0-py3-none-any.whl
Think of it as the ready-to-install package artifact.

When someone runs:

pip install dist/constellation_node_sdk-1.0.0-py3-none-any.whl
pip installs directly from that built package without needing to run your repo as a source tree.

Why wheels matter
They are:

faster to install

more reproducible

the preferred install format for most consumers

the thing you usually publish for downstream users

For your SDK, the wheel is what node repos should ideally consume.

2. Source distribution (sdist, usually .tar.gz)
A source distribution is the packaged source code of the library.

Example:

dist/constellation_node_sdk-1.0.0.tar.gz
It contains the project source and packaging metadata so someone can build/install from source.

Why sdists matter
They are useful because:

they preserve the source form of the package

some environments build from source

they are the canonical “source release”

many publishing workflows expect both wheel and sdist

So:

wheel = ready-built install artifact

sdist = packaged source artifact

What happens when you run the build
The standard command is:

python -m build
This reads your pyproject.toml and uses the configured build backend, which in your repo is:

[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"
That tells Python packaging tools:

use setuptools

build the package according to your project metadata

emit standard distribution artifacts

After running it, you should get:

dist/
├── constellation_node_sdk-1.0.0-py3-none-any.whl
└── constellation_node_sdk-1.0.0.tar.gz
Why both are important
Wheel is for installation
This is the main consumer-facing artifact.

For example:

pip install dist/constellation_node_sdk-1.0.0-py3-none-any.whl
That is how another repo can depend on your SDK without copying code.

sdist is for source-based packaging and release completeness
Some tooling or registries want the source package too.

Even if most users install the wheel, shipping the sdist is still good practice.

What the wheel name means
Example:

constellation_node_sdk-1.0.0-py3-none-any.whl
Breakdown:

constellation_node_sdk → package name normalized for artifact naming

1.0.0 → package version

py3 → compatible with Python 3

none-any → pure Python package, no platform-specific compiled binaries

That last part is good for your SDK because it means the wheel is portable.

What should be inside the wheel
Your wheel should include:

constellation_node_sdk/__init__.py

all subpackages:

transport/

security/

gate/

runtime/

orchestrator/

py.typed

If py.typed is missing, type-aware consumers lose package typing support.

You can inspect the wheel with:

python -m zipfile -l dist/constellation_node_sdk-1.0.0-py3-none-any.whl
Typical build flow
Step 1: install build tool
python -m pip install --upgrade build
Step 2: build artifacts
python -m build
Step 3: inspect outputs
ls dist
Expected:

constellation_node_sdk-1.0.0-py3-none-any.whl
constellation_node_sdk-1.0.0.tar.gz
Why you should test the wheel, not just editable install
Editable install:

pip install -e .
is great for development, but it can hide packaging mistakes because Python is importing directly from your working tree.

A real wheel install is stricter.

That catches problems like:

missing package data

missing py.typed

bad package discovery

missing modules in distribution

misconfigured pyproject.toml

So after building, do this in a clean environment:

python -m venv .venv-test
source .venv-test/bin/activate
python -m pip install --upgrade pip
python -m pip install dist/constellation_node_sdk-1.0.0-py3-none-any.whl
python -c "import constellation_node_sdk; print('ok')"
That confirms the built artifact is actually installable.

How this fits your SDK repo
For constellation-node-sdk, building wheel + sdist is how you turn the repo into a real reusable library.

Without this step, the SDK is just source code in a repo.

With it, the SDK becomes:

versioned

installable

publishable

consumable by downstream node repos

The practical mental model
Think of it like this:

your repo = workshop

wheel = finished product in a box

sdist = boxed raw materials + instructions

Most users want the finished product.
Release systems often want both.

Recommended command sequence for your repo
python -m pip install --upgrade pip setuptools wheel build
python -m pip install -e ".[dev]"
python scripts/validate_contracts.py
python scripts/generate_schema.py
ruff check src tests scripts
mypy src
pytest -q
python -m build
Then verify the built artifact:

python -m pip install dist/*.whl
Bottom line
Build wheel + sdist means:

package your library into standard Python release artifacts

produce a wheel for fast installation

produce an sdist for source-based distribution

make the SDK consumable outside the repo

For your project, this is the step that turns constellation-node-sdk from “code we wrote” into “a proper installable dependency”.

I can also write a PACKAGING_GUIDE.md file next if you want.


Which repos file does this need to be in:

[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

In the engine repos I just run the pip install command for the wheel and that’s it!? Right?

Short answer:

That block belongs only in the SDK repo (constellation-node-sdk)

Engine repos do NOT need it if they are just consuming the SDK wheel

Now let’s be precise so you don’t accidentally couple things wrong.

1. Where [build-system] goes
This goes in:

constellation-node-sdk/pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"
Why only there?
Because this section defines:

“How to build this repo into a package”

Only the SDK repo is being built into a distributable library.

2. What engine repos are (important distinction)
Your engine repos (worker nodes, orchestrators, etc.) are:

applications

not reusable libraries

not meant to be packaged and distributed (usually)

So they don’t need build configuration unless you explicitly want to package them too.

3. Engine repo behavior (what you said — yes, correct)
“In the engine repos I just run pip install for the wheel and that’s it?”

Yes. Exactly. That’s the correct model.

Example:

pip install constellation_node_sdk-1.0.0-py3-none-any.whl
Then your engine code just does:

from constellation_node_sdk import create_node_app, register_handler
No copying code. No vendoring. No shared modules.

4. What engine repos DO need
They should still have a minimal pyproject.toml (for their own deps), but not for building the SDK.

Example:

[project]
name = "score-node"
version = "1.0.0"
dependencies = [
  "constellation-node-sdk==1.0.0",
  "fastapi",
  "uvicorn"
]
That’s it.

No [build-system] required unless:

you want to package the node itself (rare)

or publish it (also rare)

5. Mental model (this is the key)
SDK repo
produces artifacts

defines protocol

is versioned dependency

has [build-system]

Engine repos
consume artifacts

implement behavior

depend on SDK

do NOT define how SDK is built

6. What NOT to do (common mistake)
❌ Don’t copy [build-system] into engine repos thinking it's required
❌ Don’t rebuild SDK inside engine repos
❌ Don’t import SDK via relative path hacks (../sdk/src)
❌ Don’t duplicate transport logic in engine repos

That breaks isolation and versioning.

7. Correct lifecycle
In SDK repo
python -m build
→ produces wheel

In engine repo
pip install constellation_node_sdk-1.0.0.whl
→ consume SDK

8. Advanced (optional but powerful)
Instead of manual wheel installs, you’ll likely move to:

Private package registry
Then engine repo just does:

dependencies = [
  "constellation-node-sdk==1.0.0"
]
and:

pip install -r requirements.txt
No local wheel handling.

9. Final answer
Where does [build-system] go?
👉 Only in constellation-node-sdk/pyproject.toml

Do engine repos need it?
👉 No (unless you’re packaging them too)

Do engine repos just install the wheel?
👉 Yes. That is exactly the intended architecture.
