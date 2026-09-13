from __future__ import annotations

import time

from trade_manager.exit_watchdog import ExitWatchdog
from trade_manager.models import Position, PositionCloseReason, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class _Repo:
    def __init__(self, position):
        self.position = position

    def get_open_positions(self):
        return [self.position]


class _Brain:
    def decide_position(self, **kwargs):
        class Decision:
            action = "SELL" if kwargs["hard_stop_triggered"] else "HOLD"
            confidence = 0.9
            reason = "policy-mirror"
            exception = None
            metadata = {}

        return Decision()


class _Facade:
    def __init__(self, position):
        self.position = position

    def execute_decision(self, position_id, decision):
        self.position.status = PositionStatus.CLOSED
        self.position.closed_at = time.time()
        self.position.realized_pnl = -0.75
        self.position.gross_pnl = -0.65
        self.position.total_fees = 0.10
        self.position.entry_fee = 0.05
        self.position.exit_fee = 0.05
        self.position.exchange_order_id = "ORDER-EXIT-1"
        self.position.close_reason = PositionCloseReason.STOP_LOSS
        return self.position


def test_exit_watchdog_records_complete_exit_trace_for_scalp_stop():
    position = Position(
        position_id="POS-TRACE-1",
        symbol="BNBUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=95.0,
        stop_loss=96.0,
        take_profit=105.0,
        opened_at=time.time() - 120,
        entry_metadata={"trade_mode": "SCALP"},
        metadata={"initial_stop_loss": 96.0, "trailing_active": True,
                  "trailing_stop_price": 99.0, "break_even_activated": False},
    )
    manager = PositionRiskManager(
        min_recovery_score=1.0,
        market_context_provider=lambda symbol: {
            "market": {"overall": "BEARISH"},
            "regime": "TREND_DOWN",
        },
    )
    watchdog = ExitWatchdog(
        repository=_Repo(position),
        risk_manager=manager,
        facade=_Facade(position),
        brain=_Brain(),
    )

    result = watchdog.run()

    assert result.evaluated == 1
    assert result.exit_signals == 1
    assert result.closed == 1
    assert result.failed == 0

    trace = watchdog.last_diagnostics[0]
    assert trace["symbol"] == "BNBUSDT"
    assert trace["trade_mode"] == "SCALP"
    assert trace["entry_price"] == 100.0
    assert trace["current_price"] == 95.0
    assert trace["stop_loss"] == 96.0
    assert trace["take_profit"] == 105.0
    assert trace["pnl_percent"] < 0
    assert trace["pnl_net"] is not None
    assert trace["recovery_mode"] is False
    assert trace["recovery_start_time"] is None
    assert trace["market_regime"] == "BEARISH"
    assert trace["decision"] == "EXIT"
    assert trace["reason"] == "STOP_LOSS"
    assert trace["execution"] == "CLOSED"
    assert trace["close_net_pnl"] == -0.75
    assert trace["close_total_fees"] == 0.10
    assert trace["close_exchange_order_id"] == "ORDER-EXIT-1"
    assert trace["close_reason"] == "STOP_LOSS"
    assert trace["evaluation_at"] > 0


def test_exit_watchdog_records_recovery_timing_and_hold_reason():
    position = Position(
        position_id="POS-TRACE-2",
        symbol="ETHUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.HOLD,
        quantity=0.5,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=96.0,
        take_profit=105.0,
        opened_at=time.time() - 600,
        entered_hold_at=time.time() - 300,
        entry_metadata={"trade_mode": "SWING"},
        hold_context={"market": {"overall": "BULLISH"}},
        hold_reason="Recovery score: 0.55 (market: 0.60)",
        metadata={"initial_stop_loss": 96.0},
    )
    manager = PositionRiskManager(
        min_recovery_score=0.0,
        market_context_provider=lambda symbol: {"market": {"overall": "BULLISH"}},
    )
    watchdog = ExitWatchdog(
        repository=_Repo(position),
        risk_manager=manager,
        facade=_Facade(position),
        brain=_Brain(),
    )

    result = watchdog.run()
    trace = watchdog.last_diagnostics[0]

    assert result.evaluated == 1
    assert result.exit_signals == 0
    assert result.closed == 0
    assert trace["trade_mode"] == "SWING"
    assert trace["recovery_mode"] is True
    assert trace["recovery_start_time"] == position.entered_hold_at
    assert trace["recovery_duration_minutes"] >= 4.0
    assert trace["decision"] == "HOLD"
    assert trace["hold_reason"]
    assert trace["market_regime"] == "BULLISH"
    assert trace["execution"] == "NOT_REQUIRED"
