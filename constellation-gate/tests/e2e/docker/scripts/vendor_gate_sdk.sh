#!/usr/bin/env bash
# Materialise the EXACT SDK commit that Constellation.Gate's requirements.lock
# pins, as a directory usable as a BuildKit named build context.
#
# WHY THIS EXISTS
# ---------------
# Gate's lock installs the SDK from a GitHub *archive tarball* URL under
# `pip --require-hashes`:
#
#   constellation-node-sdk @ https://github.com/Quantum-L9/Gate_SDK/archive/<sha>.tar.gz --hash=sha256:...
#
# This session's egress proxy serves anonymous *git* reads of public GitHub
# repositories but returns HTTP 403 for github.com/.../archive/*.tar.gz and for
# codeload.github.com. EIE and CEG install the same SDK over `git+https` and
# therefore build unmodified; Gate is the only repo that uses the archive
# endpoint, and it is the only one that cannot build here as written.
#
# The substitution is TRANSPORT ONLY. The commit installed is byte-identical to
# the locked one -- it is checked out by that exact SHA and re-verified below --
# so the SDK revision running in the Gate image is the locked revision. What is
# given up is pip's own hash check of the tarball, because the tarball cannot be
# fetched at all; git object-SHA verification replaces it. Every other
# requirement in the lock keeps --require-hashes.
#
# This is an environment accommodation, recorded in the evidence bundle under
# image_provenance.json:sdk_vendoring. It is NOT a product change: no file in
# any of the three repositories is modified.
set -Eeuo pipefail

SDK_REPO="${L9_E2E_SDK_REPO:-/home/user/quantum-l9/gate_sdk}"
OUT="${1:?usage: vendor_gate_sdk.sh <output-dir> <sha>}"
SHA="${2:?usage: vendor_gate_sdk.sh <output-dir> <sha>}"

if [[ ! -d "$SDK_REPO/.git" ]]; then
  echo "FATAL: SDK clone missing at $SDK_REPO" >&2
  exit 1
fi

# The SHA may live on a non-branch ref (a PR head); fetch it explicitly.
if ! git -C "$SDK_REPO" cat-file -t "$SHA" >/dev/null 2>&1; then
  echo "fetching $SHA by object id..."
  git -C "$SDK_REPO" fetch --quiet origin "$SHA"
fi

actual_type="$(git -C "$SDK_REPO" cat-file -t "$SHA")"
if [[ "$actual_type" != "commit" ]]; then
  echo "FATAL: $SHA is not a commit (got $actual_type)" >&2
  exit 1
fi

mkdir -p "$OUT"
# `git archive | tar -x` gives a clean export with no .git and no working-tree
# contamination -- the tree exactly as recorded at that commit.
git -C "$SDK_REPO" archive --format=tar "$SHA" | tar -x -C "$OUT"

tree_sha="$(git -C "$SDK_REPO" rev-parse "${SHA}^{tree}")"
src_sha="$(git -C "$SDK_REPO" rev-parse "${SHA}:src")"
version="$(grep -m1 -E '^version *=' "$OUT/pyproject.toml" | tr -d ' ')"

echo "vendored_sha=$SHA"
echo "vendored_root_tree=$tree_sha"
echo "vendored_src_tree=$src_sha"
echo "vendored_${version}"
echo "vendored_path=$OUT"
