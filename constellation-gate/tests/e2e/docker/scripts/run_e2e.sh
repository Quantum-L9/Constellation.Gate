#!/usr/bin/env bash
# One-command Constellation release-set system E2E on the Docker rail.
#
#   bash tests/e2e/docker/scripts/run_e2e.sh
#
# Every run starts from zero (down -v), builds nothing implicitly (images come
# from build_images.sh), and writes a timestamped, secret-free evidence bundle
# under constellation-gate/.l9/runtime/docker-e2e/<UTC timestamp>/.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$HERE")"
GATE_ROOT="$(cd "$DOCKER_DIR/../../.." && pwd)"
WORKSPACE="${L9_E2E_WORKSPACE:-/home/user}"
ENV_FILE="${ENV_FILE:-/root/l9e2e/run.env}"
COMPOSE="docker compose --env-file ${ENV_FILE} -f ${DOCKER_DIR}/compose.yml"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EV="${L9_E2E_RECEIPT_DIR:-${GATE_ROOT}/.l9/runtime/docker-e2e}/${STAMP}"
mkdir -p "$EV/flows" "$EV/logs"
echo "evidence: $EV"

jqp() { python3 -m json.tool 2>/dev/null || cat; }

# ── 0. provenance of the inputs (fail-closed) ────────────────────────────────
# Every release-set checkout must be clean and, when L9_E2E_EXPECT_<NODE>_SHA
# is set, at exactly that commit. A dirty or unexpected source stops the run
# here: a PASS over bytes that differ from the recorded commits is not proof.
python3 "${HERE}/provenance.py" sources --workspace "$WORKSPACE" \
  --out "$EV/source_revisions.json"
for r in Constellation.Gate Enrichment.Inference.Engine Cognitive.Engine.Graphs; do
  { echo "### $r"; git -C "$WORKSPACE/$r" status --short; } >> "$EV/workspace_status.txt"
done
# The one SDK commit Gate's lock resolves to; the verdict requires the Gate
# image to contain exactly this commit.
LOCK_SHA="$(python3 "${HERE}/provenance.py" sdk-lock \
  "$WORKSPACE/Constellation.Gate/constellation-gate/requirements.lock")"
printf '{"lock_sha": "%s"}\n' "$LOCK_SHA" > "$EV/sdk_lock.json"

# ── 1. clean slate ───────────────────────────────────────────────────────────
echo "== down -v =="
$COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
# `docker compose config` INTERPOLATES every variable, so its output carries
# the run's signing keys and admin token in plaintext. Stream it straight into
# the redactor: writing it to a scratch file first would leave an unredacted
# copy on disk, which redacting the bundle afterwards does not undo.
$COMPOSE config | python3 "${HERE}/redact.py" - "$EV/compose_config.yml" "${ENV_FILE}"

# ── 2. boot ──────────────────────────────────────────────────────────────────
echo "== up =="
$COMPOSE up -d --wait --wait-timeout 300 || $COMPOSE up -d

# The domain database is named after the domain spec id; CEG routes queries
# with database=<domain_id> and Neo4j does not create it implicitly.
NEO4J_PW="$(python3 -c "
import sys
for l in open('${ENV_FILE}'):
    k,_,v=l.strip().partition('=')
    if k=='L9E2E_NEO4J_PASSWORD': print(v.strip(chr(39)))")"
for i in $(seq 1 30); do
  docker exec l9e2e-neo4j cypher-shell -u neo4j -p "$NEO4J_PW" -d system \
    "CREATE DATABASE plasticos IF NOT EXISTS WAIT;" >/dev/null 2>&1 && break
  sleep 5
done
docker restart l9e2e-ceg >/dev/null 2>&1 || true

# ── 3. registration must be live, not seeded ─────────────────────────────────
echo "== await live registration =="
for i in $(seq 1 60); do
  n="$(curl -sS --noproxy '*' http://127.0.0.1:19000/v1/registry 2>/dev/null \
       | python3 -c 'import json,sys
try: print(len(json.load(sys.stdin)))
except Exception: print(0)')"
  [[ "$n" == "2" ]] && { echo "both nodes registered after ~$((i*5))s"; break; }
  sleep 5
done
curl -sS --noproxy '*' http://127.0.0.1:19000/v1/registry | jqp > "$EV/gate_registry.json"
curl -sS --noproxy '*' http://127.0.0.1:19000/v1/health   | jqp > "$EV/health_snapshot.json"

# ── 4. image + SDK provenance (read from the containers, not from lockfiles) ─
docker images --format '{{json .}}' | grep l9e2e > "$EV/image_provenance.json" || true
# The commit each image was built from (build_images.sh labels). assert_evidence
# requires these to equal the source revisions this run was bound to.
python3 - "$EV/image_revisions.json" <<'PY'
import json, subprocess, sys
out = {}
for node in ("gate", "eie", "ceg"):
    r = subprocess.run(
        ["docker", "image", "inspect", f"l9e2e/{node}:local", "--format",
         '{{index .Config.Labels "org.opencontainers.image.revision"}}'],
        capture_output=True, text=True)
    rev = r.stdout.strip()
    out[node] = rev if r.returncode == 0 and rev and rev != "<no value>" else None
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out, indent=1))
PY
python3 - "$EV/sdk_provenance.json" <<'PY'
import json, subprocess, sys
probe = (
 "import json,glob,os\n"
 "ds=sorted(glob.glob('/usr/local/lib/python*/site-packages/constellation_node_sdk-*.dist-info'))\n"
 "o={}\n"
 "for d in ds:\n"
 "    o['dist_info']=os.path.basename(d)\n"
 "    p=os.path.join(d,'direct_url.json')\n"
 "    o['direct_url']=json.load(open(p)) if os.path.exists(p) else None\n"
 "print(json.dumps(o))\n")
out = {}
for name, img in (("gate", "l9e2e/gate:local"), ("eie", "l9e2e/eie:local"), ("ceg", "l9e2e/ceg:local")):
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python", img, "-c", probe],
                       capture_output=True, text=True)
    try:
        out[name] = json.loads(r.stdout.strip() or "{}")
    except Exception:
        out[name] = {"error": (r.stderr or r.stdout)[:300]}
# Resolve each node's SDK commit from CONTAINER metadata first; the vendoring
# receipt is a last resort and only valid for a local-path install.
#
# pip records a different shape per install method:
#   git+https://...@<sha>      -> direct_url.vcs_info.commit_id
#   https://.../<sha>.tar.gz   -> direct_url.archive_info  (NO vcs_info; the
#                                 commit is in the url)
#   /local/path                -> direct_url.dir_info      (no commit at all)
#
# An earlier version only understood vcs_info, so an archive install fell
# through to the vendoring receipt and reported whatever SHA the last vendoring
# run wrote -- a commit the image did not contain. A provenance gate that is
# confidently wrong is worse than one that reports nothing, so the receipt is
# now consulted ONLY for a dir_info install.
import os, re

SHA_IN_URL = re.compile(r"/([0-9a-f]{40})\.tar\.gz$")

for node, info in out.items():
    du = (info or {}).get("direct_url") or {}
    if (du.get("vcs_info") or {}).get("commit_id"):
        continue  # git install: already authoritative
    if du.get("archive_info"):
        m = SHA_IN_URL.search(du.get("url", ""))
        if m:
            info["archive_commit_id"] = m.group(1)
            info["commit_source"] = "container archive url"
        continue
    if du.get("dir_info") is not None:
        receipt = os.path.join(os.environ.get("L9_E2E_BUILD_DIR", "/root/l9e2e/build"),
                               f"{node}.sdkvendor.txt")
        if os.path.exists(receipt):
            m = re.search(r"vendored_sha=([0-9a-f]{40})", open(receipt).read())
            if m:
                info["vendored_commit_id"] = m.group(1)
                info["commit_source"] = "vendoring receipt (local path install)"
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out, indent=1))
PY

# ── 5. scenarios ─────────────────────────────────────────────────────────────
VK="$(python3 -c "
for l in open('${ENV_FILE}'):
    k,_,v=l.strip().partition('=')
    if k=='L9E2E_VERIFYING_KEYS_JSON': print(v.strip(chr(39)))")"
GK="$(python3 -c "
for l in open('${ENV_FILE}'):
    k,_,v=l.strip().partition('=')
    if k=='L9E2E_GATE_KEY': print(v.strip(chr(39)))")"

drive() {
  local phase="$1"
  docker run --rm --network l9e2e_control \
    -v "${DOCKER_DIR}/scripts/driver.py:/driver.py:ro" \
    -e GATE_URL=http://gate:9000 -e L9_VERIFYING_KEYS_JSON="$VK" \
    -e L9E2E_DRIVER_KEY="$GK" -e L9E2E_DRIVER_KEY_ID=gate-e2e \
    -e HTTPS_PROXY= -e https_proxy= \
    --entrypoint python l9e2e/gate:local /driver.py "$phase" 2>/dev/null
}

echo "== main scenarios =="
drive main > "$EV/flows/main.json"

echo "== EIE -> Gate -> CEG (EIE's own egress) =="
docker cp "${DOCKER_DIR}/scripts/eie_egress_probe.py" l9e2e-eie:/tmp/probe.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app l9e2e-eie python /tmp/probe.py \
  > "$EV/flows/eie_to_ceg.json" 2>&1 || true

echo "== CEG -> Gate -> EIE (CEG's own egress) =="
docker cp "${DOCKER_DIR}/scripts/ceg_egress_probe.py" l9e2e-ceg:/tmp/probe.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app l9e2e-ceg python /tmp/probe.py \
  > "$EV/flows/ceg_to_eie.json" 2>&1 || true

# ── 6. topology isolation (the invariant, asserted against Docker itself) ────
echo "== isolation =="
python3 - "$EV/flows/isolation.json" <<'PY'
import json, subprocess, sys
def probe(container, host):
    r = subprocess.run(["docker", "exec", container, "getent", "hosts", host],
                       capture_output=True, text=True)
    return {"container": container, "host": host,
            "exit_code": r.returncode, "stdout": r.stdout.strip()}
res = {
  "eie_to_ceg_must_fail":  probe("l9e2e-eie", "graph"),
  "ceg_to_eie_must_fail":  probe("l9e2e-ceg", "enrichment-engine"),
  "eie_to_gate_must_work": probe("l9e2e-eie", "gate"),
  "ceg_to_gate_must_work": probe("l9e2e-ceg", "gate"),
}
res["verdict"] = ("PASS" if res["eie_to_ceg_must_fail"]["exit_code"] != 0
                  and res["ceg_to_eie_must_fail"]["exit_code"] != 0
                  and res["eie_to_gate_must_work"]["exit_code"] == 0
                  and res["ceg_to_gate_must_work"]["exit_code"] == 0 else "FAIL")
nets = {}
for n in ("l9e2e_control","l9e2e_gate_eie","l9e2e_gate_ceg","l9e2e_eie_data","l9e2e_ceg_data"):
    r = subprocess.run(["docker","network","inspect",n,"-f",
                        "{{range .Containers}}{{.Name}} {{end}}"],
                       capture_output=True, text=True)
    nets[n] = r.stdout.split()
res["network_membership"] = nets
json.dump(res, open(sys.argv[1], "w"), indent=1)
print("isolation:", res["verdict"])
PY

# ── 7. persistence ───────────────────────────────────────────────────────────
echo "== persistence =="
docker exec l9e2e-neo4j cypher-shell -u neo4j -p "$NEO4J_PW" -d plasticos \
  "MATCH (n:Facility) RETURN n.facility_id AS facility_id, n._tenant AS tenant, n.enriched_by AS enriched_by, n.e2e_marker AS marker ORDER BY facility_id;" \
  > "$EV/flows/neo4j_state.txt" 2>&1 || true
cat "$EV/flows/neo4j_state.txt"

# ── 8. outage + recovery ─────────────────────────────────────────────────────
echo "== outage =="
docker stop l9e2e-ceg >/dev/null; sleep 3
drive outage > "$EV/flows/outage.json"
curl -sS --noproxy '*' http://127.0.0.1:19000/v1/registry | jqp > "$EV/flows/registry_during_outage.json"
docker start l9e2e-ceg >/dev/null
for i in $(seq 1 40); do
  h="$(curl -sS --noproxy '*' http://127.0.0.1:19000/v1/registry 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('graph',{}).get('healthy'))
except Exception: print('none')")"
  [[ "$h" == "True" ]] && break
  sleep 5
done
drive recovery > "$EV/flows/recovery.json"

# ── 9. logs + container state ────────────────────────────────────────────────
docker logs l9e2e-gate  > "$EV/logs/gate.log" 2>&1 || true
docker logs l9e2e-eie   > "$EV/logs/eie.log"  2>&1 || true
docker logs l9e2e-ceg   > "$EV/logs/ceg.log"  2>&1 || true
docker logs l9e2e-neo4j > "$EV/logs/neo4j.log" 2>&1 || true
docker ps -a --format '{{json .}}' | grep l9e2e > "$EV/container_state.json" || true

# ── 10. verdict ──────────────────────────────────────────────────────────────
python3 "${HERE}/redact.py" --scan "$EV" "${ENV_FILE}" > "$EV/secret_scan.txt" || true
cat "$EV/secret_scan.txt"
python3 "${HERE}/assert_evidence.py" "$EV" | tee "$EV/assertions.txt"
echo "evidence bundle: $EV"
