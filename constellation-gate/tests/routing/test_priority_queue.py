from __future__ import annotations

import asyncio

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.routing.priority_queue import PriorityPacketQueue


def test_priority_queue_returns_lower_numeric_priority_first() -> None:
    async def run() -> None:
        queue = PriorityPacketQueue()

        p2_packet = create_transport_packet(
            action="enrich",
            payload={"id": "a"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=2,
        )
        p0_packet = create_transport_packet(
            action="score",
            payload={"id": "b"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=0,
        )

        await queue.put(p2_packet)
        await queue.put(p0_packet)

        first = await queue.get()
        second = await queue.get()

        assert first.header.priority == 0
        assert second.header.priority == 2

    asyncio.run(run())


def test_priority_queue_preserves_fifo_within_same_priority() -> None:
    async def run() -> None:
        queue = PriorityPacketQueue()

        first_packet = create_transport_packet(
            action="enrich",
            payload={"id": "first"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=1,
        )
        second_packet = create_transport_packet(
            action="enrich",
            payload={"id": "second"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=1,
        )

        await queue.put(first_packet)
        await queue.put(second_packet)

        first = await queue.get()
        second = await queue.get()

        assert first.payload["id"] == "first"
        assert second.payload["id"] == "second"

    asyncio.run(run())
