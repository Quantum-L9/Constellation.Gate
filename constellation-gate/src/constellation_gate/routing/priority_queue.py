from __future__ import annotations

import asyncio
from itertools import count
from typing import Any, cast

from constellation_node_sdk.transport.packet import TransportPacket


class PriorityPacketQueue:
    """
    Async priority queue for TransportPackets.

    Lower numeric priority is higher urgency:
    - 0 => P0
    - 1 => P1
    - 2 => P2
    - 3 => P3
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, TransportPacket]] = (
            asyncio.PriorityQueue()
        )
        self._sequence = count()

    async def put(self, packet: TransportPacket) -> None:
        await self._queue.put((packet.header.priority, next(self._sequence), packet))

    async def get(self) -> TransportPacket:
        _priority, _sequence, packet = await self._queue.get()
        return packet

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def drain(self) -> tuple[TransportPacket, ...]:
        items: list[TransportPacket] = []
        while not self._queue.empty():
            items.append(await self.get())
        return tuple(items)

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def debug_snapshot(self) -> tuple[dict[str, Any], ...]:
        # asyncio.PriorityQueue keeps its heap in the private `_queue` list; there
        # is no public iteration API, so read it through a cast for this debug-only
        # snapshot.
        heap = cast(list[tuple[int, int, TransportPacket]], cast(Any, self._queue)._queue)
        return tuple(
            {
                "priority": priority,
                "sequence": sequence,
                "packet_id": str(packet.header.packet_id),
                "action": packet.header.action,
            }
            for priority, sequence, packet in list(heap)
        )
