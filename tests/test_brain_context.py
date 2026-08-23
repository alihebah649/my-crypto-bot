from types import SimpleNamespace

from core.brain_context import BrainContextBuilder


def test_context_preserves_scalp_mode_from_entry_metadata():
    position = SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        current_price=99.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=105.0,
        entry_metadata={"trade_mode": "SCALP"},
        metadata={"trade_mode": "SWING"},
    )

    context = BrainContextBuilder.build(
        position,
        age_minutes=121,
        market={"ema_100": "BULLISH", "atr_percent": 1.2},
        risk={"locked": False},
        recovery={"score": 72},
        exit_policy={"decision": "HOLD"},
    )

    assert context.trade_mode == "SCALP"
    assert context.position_status == "OPEN"
    assert context.pnl_percent == -1.0
    assert context.age_minutes == 121.0
    assert context.market["ema_100"] == "BULLISH"
    assert context.recovery["score"] == 72


def test_context_falls_back_to_metadata_and_does_not_mutate_position():
    position = SimpleNamespace(
        symbol="TESTUSDT",
        status="HOLD",
        current_price=102.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={},
        metadata={"trade_mode": "SWING"},
    )

    context = BrainContextBuilder.build(position, age_minutes=-5)

    assert context.trade_mode == "SWING"
    assert context.position_status == "HOLD"
    assert context.pnl_percent == 2.0
    assert context.age_minutes == 0.0
    assert position.metadata == {"trade_mode": "SWING"}
