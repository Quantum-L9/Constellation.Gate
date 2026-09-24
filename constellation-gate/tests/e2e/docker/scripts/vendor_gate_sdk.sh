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
ROOT="${1:?usage: vendor_gate_sdk.sh <output-root> <sha>}"
SHA="${2:?usage: vendor_gate_sdk.sh <output-root> <sha>}"

# Every run materialises a FRESH tree; nothing on disk is ever reused.
# A cached tree plus a completion marker proves only that an extraction once
# finished -- not that the bytes still match the commit -- so a modified cache
# would have been installed while this script reported the requested SHA.
# `git archive` reads from the object store, where every object is verified by
# its hash, so a fresh extraction of a verified commit IS that commit.
#
# Extraction is never done in place either: `git archive | tar -x` only ADDS
# files, so extracting over an older tree would leave a mixed tree. Each run
# lands in its own staging directory that is promoted only once complete; a
# previous tree is displaced, not deleted.
TARGET="${ROOT}/${SHA}"

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

mkdir -p "$ROOT"

staging="${ROOT}/.staging.${SHA}.$$"
mkdir -p "$staging"
# `git archive | tar -x` gives a clean export with no .git and no working-tree
# contamination -- the tree exactly as recorded at that commit.
git -C "$SDK_REPO" archive --format=tar "$SHA" | tar -x -C "$staging"
if [[ -e "$TARGET" ]]; then
  mv "$TARGET" "${ROOT}/.superseded.${SHA}.$$"
fi
mv "$staging" "$TARGET"

tree_sha="$(git -C "$SDK_REPO" rev-parse "${SHA}^{tree}")"
src_sha="$(git -C "$SDK_REPO" rev-parse "${SHA}:src")"
version="$(grep -m1 -E '^version *=' "$TARGET/pyproject.toml" | tr -d ' ')"

echo "vendored_sha=$SHA"
echo "vendored_root_tree=$tree_sha"
echo "vendored_src_tree=$src_sha"
echo "vendored_${version}"
echo "vendored_path=$TARGET"
