from __future__ import annotations

import json
import logging

from constellation_gate.observability.logging import JsonLogFormatter, packet_log_context
from constellation_node_sdk.transport.packet import create_transport_packet


def test_packet_log_context_contains_lineage_and_route_fields() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    context = packet_log_context(packet)

    assert context["action"] == "score"
    assert context["source_node"] == "client"
    assert context["destination_node"] == "gate"
    assert context["generation"] == 0
    assert context["hop_count"] == 0


def test_json_log_formatter_emits_json() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="gate",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ingress",
        args=(),
        exc_info=None,
    )
    record.event = "gate.ingress"  # type: ignore[attr-defined]
    record.context = {"packet_id": "p1"}  # type: ignore[attr-defined]

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert payload["message"] == "ingress"
    assert payload["event"] == "gate.ingress"
    assert payload["packet_id"] == "p1"
