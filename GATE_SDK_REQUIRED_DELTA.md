# GATE_SDK_REQUIRED_DELTA

**Status:** `worker_transport_cleanup: BLOCKED_EXTERNAL_SDK_CAPABILITY`
**Consumer:** `Quantum-L9/Constellation.Gate`
**Provider:** `Quantum-L9/Gate_SDK`
**SDK HEAD inspected:** `d09fe58a6cd68ef8aa883896c68badc95f96e090` (branch `main`)

---

## 1. What is missing

Gate_SDK exposes **no Gate-authorized worker-packet transport primitive**.

The SDK's only outbound packet transport is `GateClient.send_to_gate`, and it is
structurally **node → Gate**, not **Gate → worker**. It cannot be reused for
dispatch, and not merely by convention — it actively rejects the shape:

| SDK guard (`gate/policy.py`) | Requires | A Gate dispatch packet has |
|---|---|---|
| `assert_node_origin_packet` | `provenance.origin_kind == "node"` | `origin_kind == "gate"` |
| `assert_node_origin_packet` | `source_node` not in `{"", "client"}` | `source_node == "gate"` (passes) |
| `assert_gate_only_destination` | `destination_node == "gate"` | `destination_node == "<worker>"` |
| `GateClientConfig` | a single fixed `gate_url` | a per-target, registry-resolved worker URL |

`GateClient` is therefore correct for what it is (the node-side rule that nodes
never call peers) and unusable for the Gate side of the same hop. There is no
second class, no lower-level packet-send helper, and no way to configure a
per-call destination.

**Consequence:** Gate must own the transport mechanics itself. They currently
live in exactly one module, `src/constellation_gate/routing/worker_transport.py`,
held there by `tests/architecture/test_worker_transport_seam.py`.

## 2. Smallest exact API that would close this

A single function is sufficient. Gate keeps the routing decision; the SDK takes
the mechanics.

```python
# constellation_node_sdk/gate/worker_transport.py

async def send_gate_authored_packet(
    packet: TransportPacket,
    *,
    worker_url: str,          # Gate-resolved. The SDK does not resolve routes.
    timeout_seconds: float,   # Remaining packet budget. Applied to the real client.
    local_gate_node: str = "gate",
    signing: GateSigningConfig | None = None,
    verify_response: bool = True,
    client: httpx.AsyncClient | None = None,   # optional pooled client
) -> TransportPacket:
    ...
```

### Required semantics

The SDK owns:

1. outbound canonical validation of a **Gate-authored** packet
   (`origin_kind == "gate"`, `source_node == local_gate_node`,
   `resolved_by_gate is True`, `destination_node != local_gate_node`);
2. signing when configured;
3. packet serialization;
4. the `POST {worker_url}/v1/execute` call;
5. **the actual network timeout**, set from `timeout_seconds`;
6. HTTP failure classification into typed errors;
7. response decoding;
8. response packet validation;
9. typed transport errors — at minimum a `WorkerUnreachable` / `WorkerTimeout` /
   `WorkerResponse` distinction, so a consumer never parses `httpx` and never
   flattens every failure into `RuntimeError`.

Gate retains: registry, resolution, derivation, admission, deadline ownership.

### The one hazard to design against

This primitive must **not** become a generic node-to-peer side door. Suggested
constraints, all enforceable inside the SDK:

- reject any packet whose `provenance.origin_kind != "gate"` — a worker node
  holding the SDK cannot use it, because its packets are never Gate-authored;
- reject `resolved_by_gate is not True`;
- keep it in a separate module from `GateClient` so node code does not import it
  incidentally, and do not re-export it from the node-facing surface.

## 3. What Gate already did in the meantime

Gate did **not** invent a permanent parallel client abstraction. It has one
narrow adapter with a single public function whose signature is deliberately
close to the API above:

```python
# constellation_gate/routing/worker_transport.py
async def post_worker_packet(*, packet, url, timeout_seconds, node_name, client=None) -> dict
```

Plus the typed error hierarchy (`WorkerTransportError` → `WorkerUnreachableError`,
`WorkerTimeoutError`, `WorkerResponseError`) that item 9 above describes.

**Migration when the SDK ships the primitive:** replace the body of
`post_worker_packet` with the SDK call and map the SDK's typed errors onto (or
delete in favor of) Gate's. `Dispatcher` does not change — it already delegates
and contains no HTTP, status mapping, or JSON decoding, which
`test_worker_transport_seam.py` asserts. The seam test's allow-list does not
change either.

## 4. Related SDK finding (already fixed upstream, was blocking Gate)

Gate was pinned to `a770e8531dc1c59ce01e1dbb0f4162785d9dda89`, in which
`TransportPacket.derive()` carried the **parent's** `hop_trace` onto the child:

```python
new_hop_trace = self.hop_trace + ((hop,) if hop is not None else ())
```

Those inherited hops are bound to the parent's `packet_id`, so
`validate_hop_trace` raises `hop packet_id does not match packet header
packet_id`. **Every dispatch packet Gate emitted was rejectable by any SDK
worker running the SDK's own inbound validation.**

SDK commit `1d52369` fixes it (`new_hop_trace = (hop,) if hop is not None else ()`)
and is present on `main`. Gate has converged its pin to `d09fe58`, and
`tests/integration/test_cross_repo_converge_round_trip.py` now proves the emitted
packet passes `validate_transport_packet` at the worker end.

**Cross-repo obligation:** `Quantum-L9/Enrichment.Inference.Engine` still pins
`a770e853` (`pyproject.toml`, `requirements-ci.txt`). The same commit also made
`transport_hash` UTC-stable; on a **non-UTC host** an old-SDK and a new-SDK node
compute different hashes for the same packet. Both sides are byte-identical on a
UTC host (verified), so containerized deployments are unaffected — but EIE should
move to `d09fe58` so the guarantee does not depend on host timezone.
