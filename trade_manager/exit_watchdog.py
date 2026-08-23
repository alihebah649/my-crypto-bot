"""Independent exit watchdog for the active Trade Manager positions.

The watchdog is deliberately separate from entry scanning. Its only job is to
walk every active position, evaluate the existing Exit Policy, and submit an
approved exit through the existing facade/execution boundary.

It does not create a second exit strategy and it cannot bypass the existing
risk/execution controls.  It also keeps a per-position diagnostic trace so a
failed/ignored exit can be diagnosed from the runtime endpoint instead of
being reduced to a single integer counter.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, List

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
        self.last_diagnostics: List[Dict[str, Any]] = []

    def run(self) -> ExitWatchdogResult:
        evaluated = exit_signals = closed = failed = 0
        diagnostics: List[Dict[str, Any]] = []

        # Snapshot the active positions first. Execution can mutate repository
        # state, so never iterate a live repository collection while closing.
        positions: List[Position] = list(self.repository.get_open_positions())

        for position in positions:
            evaluated += 1
            trace: Dict[str, Any] = {
                "position_id": position.position_id,
                "symbol": position.symbol,
                "status_before": position.status.name,
                "trade_mode": str(position.entry_metadata.get("trade_mode", "SWING")).upper(),
                "current_price": position.current_price,
                "stop_loss": position.stop_loss,
                "opened_at": position.opened_at,
                "age_minutes": max(0.0, (time.time() - position.opened_at) / 60.0),
                "decision": "NOT_RUN",
                "reason": None,
                "should_exit": False,
                "review_required": False,
                "execution": "NOT_RUN",
                "execution_message": None,
            }
            try:
                decision: PositionExitDecision = self.risk_manager.evaluate(position)
                trace.update({
                    "decision": "EXIT" if decision.should_exit else ("REVIEW" if decision.review_required else "HOLD"),
                    "reason": decision.reason.name,
                    "should_exit": decision.should_exit,
                    "review_required": decision.review_required,
                    "exit_price": decision.exit_price,
                    "message": decision.message,
                    "hold_reason": decision.hold_reason,
                    "recovery_score": decision.recovery_score,
                    "status_after_evaluation": position.status.name,
                })

                if not decision.should_exit and not decision.review_required:
                    trace["execution"] = "NOT_REQUIRED"
                    continue

                exit_signals += 1
                result = self.facade.execute_decision(position.position_id, decision)
                if result is not None and result.status.name == "CLOSED":
                    closed += 1
                    trace["execution"] = "CLOSED"
                    trace["status_after_execution"] = result.status.name
                elif decision.should_exit:
                    failed += 1
                    trace["execution"] = "FAILED"
                    trace["status_after_execution"] = getattr(result.status, "name", None) if result else None
                else:
                    trace["execution"] = "REVIEW_APPLIED"
                    trace["status_after_execution"] = getattr(result.status, "name", None) if result else None
            except Exception as exc:
                failed += 1
                trace["execution"] = "EXCEPTION"
                trace["exception"] = f"{type(exc).__name__}: {exc}"

            diagnostics.append(trace)

        self.last_diagnostics = diagnostics
        return ExitWatchdogResult(
            evaluated=evaluated,
            exit_signals=exit_signals,
            closed=closed,
            failed=failed,
        )


__all__ = ["ExitWatchdog", "ExitWatchdogResult"]
