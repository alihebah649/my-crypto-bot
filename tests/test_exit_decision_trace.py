from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason


def _position(symbol="DOTUSDT", trade_mode="SCALP", current_price=99.0, stop_loss=95.0):
    return Position(
        position_id=f"POS-{trade_mode.lower()}-{symbol.lower()}",
        symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=current_price,
        stop_loss=stop_loss,
        take_profit=None,
        entry_metadata={"trade_mode": trade_mode},
    )


def test_scalp_evaluation_persists_non_invasive_exit_trace():
    position = _position(trade_mode="SCALP")
    decision = ExitPolicyPositionRiskManager().evaluate(position)

    trace = position.metadata["exit_decision_trace"]
    assert decision.should_exit is False
    assert trace["symbol"] == "DOTUSDT"
    assert trace["position_id"] == position.position_id
    assert trace["trade_mode"] == "SCALP"
    assert trace["entry_price"] == 100.0
    assert trace["current_price"] == 99.0
    assert trace["stop_loss"] == 95.0
    assert trace["take_profit"] is None
    assert trace["decision"] in {"NONE", "HOLD", "REVIEW_REQUIRED"}
    assert trace["decision_reason"] == "NONE"
    assert "evaluation_timestamp" in trace


def test_swing_stop_loss_trace_records_exact_exit_reason():
    position = _position(
        symbol="ATOMUSDT",
        trade_mode="SWING",
        current_price=94.0,
        stop_loss=95.0,
    )
    decision = ExitPolicyPositionRiskManager().evaluate(position)

    trace = position.metadata["exit_decision_trace"]
    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.STOP_LOSS
    assert trace["trade_mode"] == "SWING"
    assert trace["decision"] == "SELL"
    assert trace["decision_reason"] == "STOP_LOSS"
    assert trace["decision_message"] == "Stop Loss / Break Even Triggered"


def test_exit_trace_is_position_specific_and_keeps_recovery_context():
    position = _position(symbol="SOLUSDT", trade_mode="SCALP", current_price=99.0)
    position.status = PositionStatus.HOLD
    position.entered_hold_at = 1_000.0
    position.hold_context = {
        "market": {"overall": "NEUTRAL"},
        "recovery_potential": 0.45,
    }

    manager = ExitPolicyPositionRiskManager()
    decision = manager.evaluate(position)

    trace = position.metadata["exit_decision_trace"]
    assert trace["position_id"] == position.position_id
    assert trace["symbol"] == "SOLUSDT"
    assert trace["trade_mode"] == "SCALP"
    assert trace["market_regime"] in {"BULLISH", "NEUTRAL", None}
    assert trace["recovery_score"] >= 0.0
    assert trace["days_in_recovery"] >= 0.0
    assert decision.reason in {
        PositionExitReason.NONE,
        PositionExitReason.RECOVERY_FAILED,
        PositionExitReason.REVIEW_REQUIRED,
    }
