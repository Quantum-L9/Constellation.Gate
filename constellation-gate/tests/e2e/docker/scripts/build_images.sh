#!/usr/bin/env bash
# Build the three Constellation node images from their OWN repository Dockerfiles.
#
# The repo Dockerfiles are not modified on disk. ca_inject.py renders a derived
# Dockerfile that adds one CA-trust layer per stage (see that file for why);
# every dependency-resolution and install instruction is preserved verbatim.
#
# --network host is required because the session's egress proxy listens on
# 127.0.0.1 and the default bridge cannot reach it.
#
# Provenance is an input contract, not a record: before anything is built every
# release-set checkout must be clean and, when L9_E2E_EXPECT_<NODE>_SHA is set,
# at exactly that commit (provenance.py sources). Each image carries the commit
# it was built from as org.opencontainers.image.revision, and run_e2e.sh fails
# the verdict unless those labels equal the sources it ran against.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$HERE")"
WORKSPACE="${L9_E2E_WORKSPACE:-/home/user}"
OUT="${L9_E2E_BUILD_DIR:-/root/l9e2e/build}"
CA_DIR="$DOCKER_DIR/ca"

mkdir -p "$OUT"

# Proxy reachable only via the host loopback; BuildKit forwards the standard
# proxy build-args into RUN environments without needing an ARG declaration,
# and does not persist them into the final image config.
PROXY="${HTTPS_PROXY:-http://127.0.0.1:37691}"
NOPROXY="${NO_PROXY:-localhost,127.0.0.1}"

# Gate's lock is the only source of the Gate SDK commit. There is no fallback
# SHA: a lock that cannot be resolved to exactly one commit stops the build.
SDK_VENDOR_ROOT="${OUT}/gate_sdk_vendor"

python3 "$HERE/provenance.py" sources --workspace "$WORKSPACE" \
  --out "${OUT}/source_revisions.json"

build_one() {
  local name="$1" context="$2" dockerfile="$3" tag="$4"
  echo "=== build ${name} :: ${tag} ==="
  python3 "$HERE/ca_inject.py" \
    --src "${context}/${dockerfile}" \
    --out "${OUT}/${name}.Dockerfile" | tee "${OUT}/${name}.cainject.txt"

  local extra_ctx=()
  if [[ "$name" == "gate" ]]; then
    # Gate's lock installs the SDK from a GitHub archive URL. Prefer that
    # pristine path: it is what production does, and pip then hash-verifies the
    # SDK like every other requirement. Vendoring is a FALLBACK for an
    # environment whose egress policy refuses the archive endpoint -- it trades
    # pip's hash check for git object verification, so it is a deviation worth
    # avoiding whenever the real path works.
    local lock_sha archive_url archive_code
    # Exactly one SDK requirement with a 40-hex archive commit, or FATAL.
    lock_sha="$(python3 "$HERE/provenance.py" sdk-lock "${context}/requirements.lock")"
    archive_url="https://github.com/Quantum-L9/Gate_SDK/archive/${lock_sha}.tar.gz"
    # --proto/--proto-redir pin both the initial request and every redirect to
    # https. The probe deliberately follows redirects (github.com hands off to
    # codeload.github.com), and without these an attacker-influenced redirect
    # could downgrade the hop to plaintext http.
    archive_code="$(curl -sS -o /dev/null -w '%{http_code}' \
                      --proto '=https' --proto-redir '=https' \
                      -L --max-time 60 "$archive_url" 2>/dev/null || echo 000)"
    if [[ "$archive_code" == "200" ]]; then
      echo "gate: SDK archive reachable (HTTP 200) — building the pristine lock path, no vendoring"
      printf 'mode=pristine\narchive_http=%s\nlock_sha=%s\n' "$archive_code" "$lock_sha" \
        > "${OUT}/gate.sdkvendor.txt"
    else
      echo "gate: SDK archive unreachable (HTTP ${archive_code}) — falling back to git vendoring"
      bash "$HERE/vendor_gate_sdk.sh" "$SDK_VENDOR_ROOT" "${lock_sha}" \
        | tee "${OUT}/gate.sdkvendor.txt"
      local sdk_path
      sdk_path="$(sed -n 's/^vendored_path=//p' "${OUT}/gate.sdkvendor.txt" | tail -1)"
      [[ -d "$sdk_path" ]] || { echo "FATAL: vendor path not reported" >&2; return 1; }
      python3 "$HERE/patch_gate_sdk.py" "${OUT}/${name}.Dockerfile"
      extra_ctx=(--build-context "l9sdk=${sdk_path}")
    fi
  fi

  local revision
  revision="$(git -C "${context}" rev-parse --verify HEAD)"

  docker buildx build \
    --network host \
    --progress plain \
    --label "org.opencontainers.image.revision=${revision}" \
    --label "io.l9.e2e.node=${name}" \
    --build-context "l9ca=${CA_DIR}" \
    "${extra_ctx[@]}" \
    --build-arg "HTTPS_PROXY=${PROXY}" \
    --build-arg "https_proxy=${PROXY}" \
    --build-arg "NO_PROXY=${NOPROXY}" \
    --build-arg "no_proxy=${NOPROXY}" \
    -f "${OUT}/${name}.Dockerfile" \
    -t "${tag}" \
    --load \
    "${context}" 2>&1 | tee "${OUT}/${name}.build.log" | tail -25

  echo "=== built ${tag} ==="
}

case "${1:-all}" in
  gate) build_one gate "${WORKSPACE}/Constellation.Gate/constellation-gate" Dockerfile l9e2e/gate:local ;;
  eie)  build_one eie  "${WORKSPACE}/Enrichment.Inference.Engine"          Dockerfile l9e2e/eie:local  ;;
  ceg)  build_one ceg  "${WORKSPACE}/Cognitive.Engine.Graphs"              Dockerfile l9e2e/ceg:local  ;;
  all)
    build_one gate "${WORKSPACE}/Constellation.Gate/constellation-gate" Dockerfile l9e2e/gate:local
    build_one eie  "${WORKSPACE}/Enrichment.Inference.Engine"          Dockerfile l9e2e/eie:local
    build_one ceg  "${WORKSPACE}/Cognitive.Engine.Graphs"              Dockerfile l9e2e/ceg:local
    ;;
  *) echo "usage: $0 [gate|eie|ceg|all]" >&2; exit 2 ;;
esac
