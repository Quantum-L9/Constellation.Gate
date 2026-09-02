"""Packet log lines carry the request-scoped context bound by the middleware."""

from __future__ import annotations

import json
import logging

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.observability.context import clear_context, set_context
from constellation_gate.observability.logging import JsonLogFormatter, log_packet_event


def test_log_packet_event_merges_request_context() -> None:
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("test.request_context")
    logger.setLevel(logging.INFO)
    handler = _Capture()
    logger.addHandler(handler)
    packet = create_transport_packet(
        action="converge",
        payload={},
        tenant="t",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    try:
        set_context(request_id="req-1", http_path="/v1/execute")
        log_packet_event(logger, event="gate.ingress", packet=packet)
    finally:
        clear_context()
        logger.removeHandler(handler)

    assert len(records) == 1
    line = json.loads(JsonLogFormatter().format(records[0]))
    assert line["request_id"] == "req-1"
    assert line["http_path"] == "/v1/execute"
    assert line["action"] == "converge"
    assert line["packet_id"] == str(packet.header.packet_id)
