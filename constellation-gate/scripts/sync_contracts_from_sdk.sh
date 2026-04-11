#!/usr/bin/env sh
set -eu

# Monorepo default: constellation-node-sdk is a sibling of this package (Gate repo root)
SDK_REPO_PATH="${SDK_REPO_PATH:-../constellation-node-sdk}"
TARGET_DIR="contracts"

cp "${SDK_REPO_PATH}/contracts/transport-packet.schema.json" "${TARGET_DIR}/transport-packet.schema.json"
cp "${SDK_REPO_PATH}/contracts/TRANSPORT_PACKET_SPEC.md" "${TARGET_DIR}/TRANSPORT_PACKET_SPEC.md"
cp "${SDK_REPO_PATH}/contracts/NODE_REGISTRATION_SPEC.md" "${TARGET_DIR}/NODE_REGISTRATION_SPEC.md"
cp "${SDK_REPO_PATH}/contracts/ROUTING_POLICY_SPEC.md" "${TARGET_DIR}/ROUTING_POLICY_SPEC.md"

echo "contracts synchronized from ${SDK_REPO_PATH}"
