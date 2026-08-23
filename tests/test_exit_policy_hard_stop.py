from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason, PositionRiskManager


def test_stop_loss_precedes_smart_hold_even_when_recovery_is_strong():
    position = Position(
        position_id="HARD-STOP-001",
        symbol="RENDERUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=33.0,
        entry_price=1.486,
        current_price=1.439,
        stop_loss=1.440,
        take_profit=None,
    )

    manager = PositionRiskManager(
        market_context_provider=lambda _symbol: {
            "market": {"overall": "BULLISH"},
        },
        ema_provider=lambda _symbol: {"trend": "BULLISH"},
        atr_provider=lambda _symbol: {"volatility": "LOW", "percent": 0.4},
        btc_trend_provider=lambda: "BULLISH",
        min_recovery_score=0.40,
    )

    decision = manager.evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.STOP_LOSS
    assert decision.reason is not PositionExitReason.RECOVERY_FAILED
    assert position.status is PositionStatus.OPEN


def test_smart_hold_still_applies_when_stop_has_not_triggered():
    position = Position(
        position_id="HOLD-001",
        symbol="AVAXUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=6.0,
        entry_price=7.50,
        current_price=7.45,
        stop_loss=7.30,
        take_profit=None,
    )

    manager = PositionRiskManager(
        market_context_provider=lambda _symbol: {"market": {"overall": "BULLISH"}},
        ema_provider=lambda _symbol: {"trend": "BULLISH"},
        atr_provider=lambda _symbol: {"volatility": "LOW", "percent": 0.4},
        btc_trend_provider=lambda: "BULLISH",
        min_recovery_score=0.40,
    )

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.hold_reason
    assert position.status is PositionStatus.HOLD
