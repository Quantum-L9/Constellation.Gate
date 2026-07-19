from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class TimeoutPolicy:
    def __init__(self, default_timeout_ms: int = 30_000) -> None:
        self.default_timeout_ms = default_timeout_ms

    def resolve(self, packet: TransportPacket) -> float:
        return (packet.header.timeout_ms or self.default_timeout_ms) / 1000.0
