"""Independent exit watchdog for the active Trade Manager positions.

The watchdog is deliberately separate from entry scanning. Its only job is to
walk every active position, evaluate the existing Exit Policy, and submit an
approved exit through the existing facade/execution boundary.

The Brain is advisory only: its recommendation is recorded for comparison and
analysis, but it never replaces the authoritative Risk/Exit decision.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, List

from core.brain_context import BrainContextBuilder
from core.brain_decision import BrainDecisionEngine
from core.brain_metrics import BrainMetrics

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
    """Run exit evaluation independently from entry/strategy scanning."""

    def __init__(self, *, repository, risk_manager: PositionRiskManager,
                 facade: PositionManagementFacade,
                 brain: BrainDecisionEngine | None = None) -> None:
        self.repository = repository
        self.risk_manager = risk_manager
        self.facade = facade
        self.brain = brain or BrainDecisionEngine()
        self.metrics = BrainMetrics()
        self.last_diagnostics: List[Dict[str, Any]] = []

    def run(self) -> ExitWatchdogResult:
        evaluated = exit_signals = closed = failed = 0
        diagnostics: List[Dict[str, Any]] = []
        self.metrics = BrainMetrics()
        positions: List[Position] = list(self.repository.get_open_positions())

        for position in positions:
            evaluated += 1
            age_minutes = max(0.0, (time.time() - position.opened_at) / 60.0)
            pnl_percent = 0.0
            if position.entry_price > 0:
                pnl_percent = ((position.current_price - position.entry_price) / position.entry_price) * 100.0

            trace: Dict[str, Any] = {
                "position_id": position.position_id,
                "symbol": position.symbol,
                "status_before": position.status.name,
                "trade_mode": str(
                    position.entry_metadata.get(
                        "trade_mode",
                        position.metadata.get("trade_mode", "SWING"),
                    )
                ).upper(),
                "current_price": position.current_price,
                "stop_loss": position.stop_loss,
                "opened_at": position.opened_at,
                "age_minutes": age_minutes,
                "pnl_percent": pnl_percent,
                "decision": "NOT_RUN",
                "reason": None,
                "should_exit": False,
                "review_required": False,
                "execution": "NOT_RUN",
                "execution_message": None,
                "brain_action": None,
                "brain_confidence": None,
                "brain_reason": None,
                "brain_exception": None,
                "brain_authority": "ADVISORY",
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

                context = BrainContextBuilder.build(
                    position,
                    age_minutes=age_minutes,
                    recovery={"score": decision.recovery_score, "active": decision.recovery_score > 0},
                    exit_policy={
                        "decision": trace["decision"],
                        "reason": decision.reason.name,
                        "review_required": decision.review_required,
                        "hold_reason": decision.hold_reason,
                    },
                    risk={"exit_authority": "PositionRiskManager"},
                )
                brain_decision = self.brain.decide_position(
                    pnl_percent=context.pnl_percent,
                    hard_stop_triggered=decision.reason.name == "STOP_LOSS",
                    take_profit_triggered=decision.reason.name == "TAKE_PROFIT",
                    recovery_active=bool(context.recovery.get("active")) and context.pnl_percent < 0,
                    recovery_score=float(context.recovery.get("score", 0.0)),
                    exit_signal="SELL" if decision.should_exit else "HOLD",
                    age_minutes=context.age_minutes,
                )
                self.metrics.record(
                    brain_action=brain_decision.action,
                    policy_exit=decision.should_exit,
                    review_required=decision.review_required,
                )
                trace.update({
                    "brain_context": context.to_dict(),
                    "brain_action": brain_decision.action,
                    "brain_confidence": brain_decision.confidence,
                    "brain_reason": brain_decision.reason,
                    "brain_exception": brain_decision.exception,
                    "brain_metadata": dict(brain_decision.metadata),
                    "brain_agrees_with_policy": (
                        (brain_decision.action == "SELL") == decision.should_exit
                        if not decision.review_required
                        else None
                    ),
                })

                if not decision.should_exit and not decision.review_required:
                    trace["execution"] = "NOT_REQUIRED"
                    diagnostics.append(trace)
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
