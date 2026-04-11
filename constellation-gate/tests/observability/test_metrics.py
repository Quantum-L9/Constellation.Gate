from __future__ import annotations

from constellation_gate.observability.metrics import (
    DISPATCHES_TOTAL,
    IN_FLIGHT,
    REQUESTS_TOTAL,
    decrement_in_flight,
    increment_in_flight,
    record_dispatch,
    record_request,
)


def test_record_request_increments_counter() -> None:
    before = REQUESTS_TOTAL.labels(action="score", status="completed")._value.get()  # noqa: SLF001
    record_request(action="score", status="completed")
    after = REQUESTS_TOTAL.labels(action="score", status="completed")._value.get()  # noqa: SLF001

    assert after == before + 1


def test_record_dispatch_increments_counter() -> None:
    before = DISPATCHES_TOTAL.labels(action="score", target_node="score", status="delegated")._value.get()  # noqa: SLF001
    record_dispatch(action="score", target_node="score", status="delegated")
    after = DISPATCHES_TOTAL.labels(action="score", target_node="score", status="delegated")._value.get()  # noqa: SLF001

    assert after == before + 1


def test_in_flight_gauge_changes() -> None:
    before = IN_FLIGHT._value.get()  # noqa: SLF001
    increment_in_flight()
    mid = IN_FLIGHT._value.get()  # noqa: SLF001
    decrement_in_flight()
    after = IN_FLIGHT._value.get()  # noqa: SLF001

    assert mid == before + 1
    assert after == before
