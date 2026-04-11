from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


@dataclass(frozen=True)
class ExecutionContext:
    local_node: str
    request_id: str | None = None


@dataclass(frozen=True)
class ExecuteCommand:
    packet: TransportPacket
    context: ExecutionContext


class CommandFactory:
    """
    Factory converting validated packets into execution commands.

    This creates an explicit command boundary between ingress validation and
    service execution, making the execute path easier to test and extend.
    """

    def build(self, *, packet: TransportPacket, context: ExecutionContext) -> ExecuteCommand:
        return ExecuteCommand(packet=packet, context=context)

    def from_body(
        self,
        *,
        body: dict[str, Any],
        validator,
        context: ExecutionContext,
    ) -> ExecuteCommand:
        packet = validator.validate(body)
        return self.build(packet=packet, context=context)
