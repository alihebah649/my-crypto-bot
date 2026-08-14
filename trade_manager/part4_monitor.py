"""Trade Manager Part 4 monitoring loop.

Monitoring obtains market data, asks the protection layer for a decision,
and delegates execution/update work to an injected executor. It never
invents an exit decision and never talks directly to an exchange.
"""
from __future__ import annotations
import threading, time
from dataclasses import dataclass

@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    last_price: float
    atr: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume: float = 0.0
    timestamp: float = 0.0

class PositionMonitor:
    def __init__(self, repository, market_provider, protection_executor):
        self.repository = repository
        self.market_provider = market_provider
        self.protection_executor = protection_executor
        self._lock = threading.RLock()

    def monitor_once(self, cycle_number: int = 0) -> None:
        with self._lock:
            positions = list(self.repository.get_open_positions())
        for position in positions:
            try:
                snapshot = self.market_provider.get_snapshot(position.symbol)
                if snapshot is None:
                    continue
                self.protection_executor.process(
                    position=position, market_snapshot=snapshot, cycle_number=cycle_number
                )
            except Exception:
                continue

class PositionMonitorThread(threading.Thread):
    def __init__(self, monitor: PositionMonitor, interval_seconds: float = 1.0):
        super().__init__(daemon=True, name="PositionMonitorThread")
        self.monitor = monitor
        self.interval = max(0.1, float(interval_seconds))
        self._running = threading.Event()
        self._running.set()
        self.cycle_counter = 0

    def stop(self) -> None:
        self._running.clear()

    def run(self) -> None:
        while self._running.is_set():
            self.cycle_counter += 1
            started = time.monotonic()
            self.monitor.monitor_once(self.cycle_counter)
            remaining = self.interval - (time.monotonic() - started)
            if remaining > 0:
                self._running.wait(remaining)
