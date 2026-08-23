"""Independent exit watchdog for the active Trade Manager positions.

The watchdog is deliberately separate from entry scanning. Its only job is to
walk every active position, evaluate the existing Exit Policy, and submit an
approved exit through the existing facade/execution boundary.

It does not create a second exit strategy and it cannot bypass the existing
risk/execution controls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .facade import PositionManagementFacade
from .models import Position
from .risk_manager import PositionExitDecision, PositionRiskManager


@dataclass(frozen=True, slots=True)
class ExitWatchdogResult:
    evaluated: int = 0
    exit_signals: int = 0
    closed: int = 0
    failed: int = 0


class ExitWatchdog:
    """Run exit evaluation independently of entry/strategy scanning."""

    def __init__(self, *, repository, risk_manager: PositionRiskManager,
                 facade: PositionManagementFacade) -> None:
        self.repository = repository
        self.risk_manager = risk_manager
        self.facade = facade

    def run(self) -> ExitWatchdogResult:
        evaluated = exit_signals = closed = failed = 0
        # Snapshot the active positions first. Execution can mutate repository
        # state, so never iterate a live repository collection while closing.
        positions: List[Position] = list(self.repository.get_open_positions())

        for position in positions:
            evaluated += 1
            try:
                decision: PositionExitDecision = self.risk_manager.evaluate(position)
                if not decision.should_exit and not decision.review_required:
                    continue
                exit_signals += 1
                result = self.facade.execute_decision(position.position_id, decision)
                if result is not None and result.status.name == "CLOSED":
                    closed += 1
                elif decision.should_exit:
                    failed += 1
            except Exception:
                failed += 1

        return ExitWatchdogResult(
            evaluated=evaluated,
            exit_signals=exit_signals,
            closed=closed,
            failed=failed,
        )


__all__ = ["ExitWatchdog", "ExitWatchdogResult"]
