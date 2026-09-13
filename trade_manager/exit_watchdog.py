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

    @staticmethod
    def _trade_mode(position: Position) -> str:
        return str(
            position.entry_metadata.get(
                "trade_mode",
                position.metadata.get("trade_mode", "SWING"),
            )
        ).upper()

    @staticmethod
    def _market_regime(position: Position) -> Any:
        context = position.hold_context or {}
        market = context.get("market")
        if isinstance(market, dict) and market.get("overall") is not None:
            return market.get("overall")
        return context.get("overall_regime", context.get("regime"))

    @staticmethod
    def _recovery_start(position: Position) -> float | None:
        return position.entered_hold_at

    @staticmethod
    def _trailing_level(position: Position) -> Any:
        for key in ("trailing_stop", "trailing_stop_price", "trailing_level"):
            if key in position.metadata:
                return position.metadata[key]
        return None

    def run(self) -> ExitWatchdogResult:
        evaluated = exit_signals = closed = failed = 0
        diagnostics: List[Dict[str, Any]] = []
        self.metrics = BrainMetrics()
        positions: List[Position] = list(self.repository.get_open_positions())

        for position in positions:
            evaluated += 1
            evaluation_at = time.time()
            age_minutes = max(0.0, (evaluation_at - position.opened_at) / 60.0)
            pnl_percent = 0.0
            if position.entry_price > 0:
                pnl_percent = ((position.current_price - position.entry_price) / position.entry_price) * 100.0

            recovery_start = self._recovery_start(position)
            recovery_duration_minutes = (
                max(0.0, (evaluation_at - recovery_start) / 60.0)
                if recovery_start is not None else 0.0
            )
            initial_stop = position.metadata.get("initial_stop_loss", position.stop_loss)
            trace: Dict[str, Any] = {
                "position_id": position.position_id,
                "symbol": position.symbol,
                "status_before": position.status.name,
                "trade_mode": self._trade_mode(position),
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "stop_loss": position.stop_loss,
                "initial_stop_loss": initial_stop,
                "take_profit": position.take_profit,
                "opened_at": position.opened_at,
                "evaluation_at": evaluation_at,
                "age_minutes": age_minutes,
                "pnl_percent": pnl_percent,
                "pnl_net": None,
                "trailing_active": bool(
                    position.metadata.get("trailing_active", False)
                    or self._trailing_level(position) is not None
                ),
                "trailing_level": self._trailing_level(position),
                "break_even_active": bool(position.metadata.get("break_even_activated", False)),
                "recovery_mode": bool(position.entered_hold_at is not None),
                "recovery_start_time": recovery_start,
                "recovery_duration_minutes": recovery_duration_minutes,
                "recovery_score": 0.0,
                "market_regime": self._market_regime(position),
                "decision": "NOT_RUN",
                "reason": None,
                "should_exit": False,
                "review_required": False,
                "hold_reason": None,
                "execution": "NOT_RUN",
                "execution_message": None,
                "close_pnl": None,
                "close_net_pnl": None,
                "close_total_fees": None,
                "close_entry_fee": None,
                "close_exit_fee": None,
                "close_exchange_order_id": None,
                "brain_action": None,
                "brain_confidence": None,
                "brain_reason": None,
                "brain_exception": None,
                "brain_authority": "ADVISORY",
            }
            try:
                # Use the authoritative calculator for fee-aware unrealized net P&L.
                try:
                    calculation = self.risk_manager.calculator.calculate(position)
                    trace["pnl_net"] = calculation.net_pnl
                except Exception:
                    pass

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
                    "market_context_after_evaluation": dict(position.hold_context or {}),
                })
                if trace["recovery_start_time"] is None and position.entered_hold_at is not None:
                    trace["recovery_start_time"] = position.entered_hold_at
                    trace["recovery_mode"] = True
                    trace["recovery_duration_minutes"] = max(
                        0.0, (evaluation_at - position.entered_hold_at) / 60.0
                    )
                trace["market_regime"] = self._market_regime(position)
                trace["trailing_active"] = bool(
                    position.metadata.get("trailing_active", False)
                    or self._trailing_level(position) is not None
                )
                trace["trailing_level"] = self._trailing_level(position)
                trace["break_even_active"] = bool(position.metadata.get("break_even_activated", False))

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
                    trace["close_pnl"] = result.gross_pnl
                    trace["close_net_pnl"] = result.realized_pnl
                    trace["close_total_fees"] = result.total_fees
                    trace["close_entry_fee"] = result.entry_fee
                    trace["close_exit_fee"] = result.exit_fee
                    trace["close_exchange_order_id"] = result.exchange_order_id
                    trace["closed_at"] = result.closed_at
                    trace["close_reason"] = result.close_reason.name
                    trace["execution_message"] = decision.message
                elif decision.should_exit:
                    failed += 1
                    trace["execution"] = "FAILED"
                    trace["status_after_execution"] = getattr(result.status, "name", None) if result else None
                    trace["execution_message"] = getattr(result, "message", None) or decision.message
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
