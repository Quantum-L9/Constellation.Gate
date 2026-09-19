#!/usr/bin/env bash
# Generate ephemeral credentials for one E2E run.
#
# Every identity gets its OWN secret -- the existing process-rail seam harness
# shares a single secret across all three key ids, which cannot distinguish
# "verified with the right key" from "verified with any key". A per-identity
# secret means key-id resolution is actually exercised.
#
# The generated file is written OUTSIDE the repository tree and is never
# copied into the evidence bundle. Only key IDs are recorded as evidence.
set -Eeuo pipefail

OUT="${1:-/root/l9e2e/run.env}"
mkdir -p "$(dirname "$OUT")"

gate_key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
eie_key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
ceg_key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
admin="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
neo4j_pw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18).replace("-","x").replace("_","y"))')"
# EIE's Postgres is an ephemeral, network-isolated fixture with no published
# port, but a literal credential in a tracked file is still a literal
# credential -- generate it like every other secret.
pg_pw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18).replace("-","x").replace("_","y"))')"

verifying="$(python3 -c '
import json, sys
print(json.dumps({"gate-e2e": sys.argv[1], "eie-e2e": sys.argv[2], "ceg-e2e": sys.argv[3]}))
' "$gate_key" "$eie_key" "$ceg_key")"

umask 077
cat > "$OUT" <<EOF
L9E2E_GATE_KEY=${gate_key}
L9E2E_EIE_KEY=${eie_key}
L9E2E_CEG_KEY=${ceg_key}
L9E2E_ADMIN_TOKEN=${admin}
L9E2E_NEO4J_PASSWORD=${neo4j_pw}
L9E2E_PG_PASSWORD=${pg_pw}
L9E2E_VERIFYING_KEYS_JSON=${verifying}
EOF

echo "wrote ${OUT}"
echo "key_ids=gate-e2e,eie-e2e,ceg-e2e (distinct secrets per identity)"
echo "secrets_printed=false"
