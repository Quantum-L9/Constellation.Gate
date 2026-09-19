#!/usr/bin/env bash
# Build the three Constellation node images from their OWN repository Dockerfiles.
#
# The repo Dockerfiles are not modified on disk. ca_inject.py renders a derived
# Dockerfile that adds one CA-trust layer per stage (see that file for why);
# every dependency-resolution and install instruction is preserved verbatim.
#
# --network host is required because the session's egress proxy listens on
# 127.0.0.1 and the default bridge cannot reach it.
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

# Gate's lock pins the SDK by an archive URL this session's proxy refuses, so
# the Gate build needs the commit exported over git first. EIE and CEG install
# the SDK over git+https and need nothing extra.
GATE_SDK_SHA="${L9_E2E_GATE_SDK_SHA:-2b2f53a28a59bbfb2fa45f5eac32b722d802209a}"
SDK_VENDOR="${OUT}/gate_sdk_vendor"

build_one() {
  local name="$1" context="$2" dockerfile="$3" tag="$4"
  echo "=== build ${name} :: ${tag} ==="
  python3 "$HERE/ca_inject.py" \
    --src "${context}/${dockerfile}" \
    --out "${OUT}/${name}.Dockerfile" | tee "${OUT}/${name}.cainject.txt"

  local extra_ctx=()
  if [[ "$name" == "gate" ]]; then
    bash "$HERE/vendor_gate_sdk.sh" "$SDK_VENDOR" "$GATE_SDK_SHA" \
      | tee "${OUT}/gate.sdkvendor.txt"
    python3 "$HERE/patch_gate_sdk.py" "${OUT}/${name}.Dockerfile"
    extra_ctx=(--build-context "l9sdk=${SDK_VENDOR}")
  fi

  docker buildx build \
    --network host \
    --progress plain \
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
