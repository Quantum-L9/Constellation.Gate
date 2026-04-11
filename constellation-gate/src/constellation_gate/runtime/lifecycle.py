from __future__ import annotations

import logging

logger = logging.getLogger("constellation_gate.runtime.lifecycle")


class LifecycleManager:
    def __init__(self) -> None:
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started:
            return
        logger.info("gate.lifecycle.start")
        self._started = True

    def stop(self) -> None:
        if self._stopped:
            return
        logger.info("gate.lifecycle.stop")
        self._stopped = True

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopped(self) -> bool:
        return self._stopped
