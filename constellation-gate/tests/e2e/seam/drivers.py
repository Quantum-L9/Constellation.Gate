"""Driver scripts executed *inside* the peer interpreters (see harness.run_in_peer).

Each driver reads its arguments from the SEAM_ARGS environment variable (JSON)
and prints one JSON object. Production paths are used for the happy-path
directions (EIE PacketRouter / GraphSyncClient, CEG gate_egress); the raw
httpx calls exist only to *inject* the failures the seam must reject.
"""

from __future__ import annotations

EIE_DRIVER = r"""
import asyncio, json, os, sys
import httpx
args = json.loads(os.environ["SEAM_ARGS"])
op = args["op"]

def out(obj):
    print(json.dumps(obj, default=str))

async def main():
    from app.core.config import get_settings
    settings = get_settings()
    if op == "sync":
        from app.engines.packet_router import get_router, NodeUnreachableError
        router = get_router(settings)
        try:
            res = await router.notify_graph_sync(args["tenant"], args["entity_id"], args["fields"], domain=args["tenant"], correlation_id=args.get("correlation_id"))
            out({"ok": res is not None, "result": res})
        except Exception as exc:
            out({"ok": False, "error": type(exc).__name__, "detail": str(exc)})
    elif op == "route":
        from app.engines.packet_router import get_router, NodeTarget, NodeUnreachableError
        router = get_router(settings)
        try:
            res = await router.route(NodeTarget.GRAPH, args["action"], args["tenant"], args["payload"], args.get("correlation_id"), idempotency_key=args.get("idempotency_key"))
            out({"ok": True, "result": res})
        except NodeUnreachableError as exc:
            cause = exc.__cause__
            out({"ok": False, "error": type(exc).__name__, "detail": str(exc), "cause": type(cause).__name__ if cause else None, "cause_detail": str(cause) if cause else None, "status_code": getattr(cause, "status_code", None)})
    elif op in ("gsc_sync", "gsc_match", "gsc_outcome"):
        from app.engines.graph_sync_client import GraphSyncClient
        client = GraphSyncClient(settings.gate_url)
        if op == "gsc_sync":
            res = await client.sync_entities(args["entity_type"], args["batch"], args["tenant"], idempotency_key=args.get("idempotency_key"))
        elif op == "gsc_match":
            res = await client.match(args["query"], args["match_direction"], args["tenant"], top_n=args.get("top_n", 5))
        else:
            res = await client.send_outcome(args["outcome"], args["tenant"], idempotency_key=args.get("idempotency_key"))
        out({"ok": res.get("status") != "failed", "result": res})
    elif op == "exec_raw":
        from constellation_node_sdk import GateClientError
        from app.services.gate_client import build_gate_client
        client = build_gate_client(settings.gate_url, timeout_seconds=float(args.get("timeout_seconds", 10.0)))
        try:
            resp = await client.execute(action=args["action"], payload=args["payload"], tenant=args["tenant"], idempotency_key=args.get("idempotency_key"), timeout_ms=args.get("timeout_ms"), correlation_id=args.get("correlation_id"))
            out({"ok": resp.header.packet_type != "failure", "packet": resp.model_dump_json_dict()})
        except GateClientError as exc:
            out({"ok": False, "error": type(exc).__name__, "detail": str(exc), "status_code": getattr(exc, "status_code", None)})
    elif op == "replay":
        from constellation_node_sdk import GateClientError, create_transport_packet
        from constellation_node_sdk.transport.provenance import RoutingProvenance
        from app.services.gate_client import build_gate_client
        client = build_gate_client(settings.gate_url, timeout_seconds=10.0)
        packet = create_transport_packet(action=args["action"], payload=args["payload"], tenant=args["tenant"], destination_node="gate", source_node="enrichment-engine", reply_to="enrichment-engine", idempotency_key=args.get("idempotency_key"), provenance=RoutingProvenance(origin_kind="node", requested_action=args["action"], resolved_by_gate=False, original_source_node="enrichment-engine"))
        results = []
        for _ in range(2):
            try:
                resp = await client.send_to_gate(packet)
                results.append({"ok": True, "packet_id": str(resp.header.packet_id), "packet_type": resp.header.packet_type})
            except GateClientError as exc:
                results.append({"ok": False, "error": type(exc).__name__, "detail": str(exc), "status_code": getattr(exc, "status_code", None)})
        out({"ok": True, "attempts": results, "sent_packet_id": str(packet.header.packet_id)})
    elif op in ("post_unsigned", "post_direct"):
        from constellation_node_sdk import create_transport_packet
        from constellation_node_sdk.transport.provenance import RoutingProvenance
        dest = "gate" if op == "post_unsigned" else args["destination_node"]
        packet = create_transport_packet(action=args["action"], payload=args["payload"], tenant=args["tenant"], destination_node=dest, source_node="enrichment-engine", reply_to="enrichment-engine", provenance=RoutingProvenance(origin_kind="node", requested_action=args["action"], resolved_by_gate=False, original_source_node="enrichment-engine"))
        body = packet.model_dump_json_dict()
        url = args["url"]
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, json=body)
        try:
            body_json = r.json()
        except Exception:
            body_json = None
        out({"ok": True, "status_code": r.status_code, "body": r.text[:600], "body_json": body_json, "packet_id": str(packet.header.packet_id)})
    elif op == "post_malformed":
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(args["url"], content=args["body"].encode(), headers={"content-type": "application/json"})
        out({"ok": True, "status_code": r.status_code, "body": r.text[:600]})
    else:
        out({"ok": False, "error": "unknown_op", "op": op})

asyncio.run(main())
"""

CEG_DRIVER = r"""
import asyncio, json, os
import httpx
args = json.loads(os.environ["SEAM_ARGS"])
op = args["op"]

def out(obj):
    print(json.dumps(obj, default=str))

async def main():
    if op == "enrich":
        from engine.gate_egress import request_enrichment
        res = await request_enrichment(tenant=args["tenant"], entity_id=args["entity_id"], domain=args["domain"], target_fields=args["target_fields"], entity=args.get("entity"), timeout_ms=args.get("timeout_ms", 25000), correlation_id=args.get("correlation_id"))
        out({"ok": res.get("status") == "ok", "result": res})
    elif op == "trigger":
        from engine.config.loader import DomainPackLoader
        from engine.health.enrichment_trigger import trigger_reenrichment_v2
        from engine.health.field_health import EntityHealth, EnrichmentTarget
        loader = DomainPackLoader(config_path=os.environ["DOMAINS_ROOT"])
        spec = loader.load_domain(args["tenant"])
        health = EntityHealth(**args["entity_health"])
        res = await trigger_reenrichment_v2(health, spec, args["tenant"])
        out({"ok": bool(res.get("triggered")), "result": res})
    elif op == "post_direct":
        from constellation_node_sdk import create_transport_packet
        from constellation_node_sdk.transport.provenance import RoutingProvenance
        packet = create_transport_packet(action=args["action"], payload=args["payload"], tenant=args["tenant"], destination_node=args["destination_node"], source_node="graph", reply_to="graph", provenance=RoutingProvenance(origin_kind="node", requested_action=args["action"], resolved_by_gate=False, original_source_node="graph"))
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(args["url"], json=packet.model_dump_json_dict())
        try:
            body_json = r.json()
        except Exception:
            body_json = None
        out({"ok": True, "status_code": r.status_code, "body": r.text[:600], "body_json": body_json, "packet_id": str(packet.header.packet_id)})
    elif op == "cypher":
        from neo4j import GraphDatabase
        with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])) as driver:
            records, _, _ = driver.execute_query(args["cypher"], args.get("parameters", {}), database_=args.get("database", "plasticos"))
            out({"ok": True, "rows": [dict(r) for r in records]})
    else:
        out({"ok": False, "error": "unknown_op", "op": op})

asyncio.run(main())
"""
