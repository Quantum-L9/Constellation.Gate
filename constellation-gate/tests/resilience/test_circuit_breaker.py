from __future__ import annotations

import pytest

from constellation_gate.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failure_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10.0)

    async def fail():
        raise TimeoutError("temporary")

    with pytest.raises(TimeoutError):
        await breaker.run(fail)
    with pytest.raises(TimeoutError):
        await breaker.run(fail)

    with pytest.raises(CircuitBreakerOpenError):
        breaker.before_call(now=100.0)

    assert breaker.snapshot.state == "open"


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_then_closes_on_success() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5.0)

    async def fail():
        raise TimeoutError("temporary")

    async def succeed():
        return "ok"

    with pytest.raises(TimeoutError):
        await breaker.run(fail)

    with pytest.raises(CircuitBreakerOpenError):
        breaker.before_call(now=1.0)

    breaker.before_call(now=6.1)
    assert breaker.snapshot.state == "half_open"

    result = await breaker.run(succeed)
    assert result == "ok"
    assert breaker.snapshot.state == "closed"
    assert breaker.snapshot.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_reopens_on_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5.0)

    async def fail():
        raise TimeoutError("temporary")

    with pytest.raises(TimeoutError):
        await breaker.run(fail)

    breaker.before_call(now=6.0)
    assert breaker.snapshot.state == "half_open"

    breaker.record_failure(now=6.0)

    assert breaker.snapshot.state == "open"
