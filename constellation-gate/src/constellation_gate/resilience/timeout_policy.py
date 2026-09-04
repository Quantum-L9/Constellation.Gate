from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class TimeoutPolicy:
    """Gate's own wait on one packet, derived from the packet's advertised budget.

    ``response_margin_ms`` is the slice of that budget Gate keeps for itself so
    that, when the worker does not answer in time, Gate's 504 is produced
    BEFORE the caller's socket deadline. The SDK sets the caller's socket
    deadline to exactly the advertised budget, so with no margin Gate's answer
    and the caller's timeout race and the caller never sees the 504. The margin
    is only applied when the budget can afford it: a budget at or below twice
    the margin is used whole.
    """

    def __init__(self, default_timeout_ms: int = 30_000, *, response_margin_ms: int = 0) -> None:
        if response_margin_ms < 0:
            raise ValueError("response_margin_ms must be >= 0")
        self.default_timeout_ms = default_timeout_ms
        self.response_margin_ms = response_margin_ms

    def budget_ms(self, packet: TransportPacket) -> int:
        """Gate's wait for this packet, in milliseconds, after the margin."""
        advertised = packet.header.timeout_ms or self.default_timeout_ms
        if self.response_margin_ms and advertised > 2 * self.response_margin_ms:
            return advertised - self.response_margin_ms
        return advertised

    def resolve(self, packet: TransportPacket) -> float:
        return self.budget_ms(packet) / 1000.0
