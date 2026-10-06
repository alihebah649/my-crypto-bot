from core.brain_engine import TradingBrain
from core.brain_models import (
    BrainAction,
    BrainMarketState,
    BrainPosition,
    BrainRiskState,
)


def test_hard_stop_cannot_be_overridden_by_hold_logic():
    decision = TradingBrain().decide(
        market=BrainMarketState(symbol="TESTUSDT", signal="HOLD"),
        risk=BrainRiskState(),
        position=BrainPosition(symbol="TESTUSDT", hard_stop=True),
    )
    assert decision.action is BrainAction.EXIT
    assert decision.hard_constraint is True
    assert decision.reason == "HARD_STOP_PRIORITY"


def test_scalp_timeout_is_authoritative_exit():
    decision = TradingBrain().decide(
        market=BrainMarketState(symbol="TESTUSDT", signal="BUY", scalp_score=90),
        risk=BrainRiskState(),
        position=BrainPosition(symbol="TESTUSDT", trade_mode="SCALP", timeout=True),
    )
    assert decision.action is BrainAction.EXIT
    assert decision.hard_constraint is True
    assert decision.reason == "SCALP_TIMEOUT_PRIORITY"


def test_daily_risk_lock_blocks_new_entry():
    decision = TradingBrain().decide(
        market=BrainMarketState(symbol="ADAUSDT", signal="BUY", scalp_score=90, confirmed_reversal=True, macro_support=True),
        risk=BrainRiskState(locked=True, lock_reason="DAILY_LOSS_LIMIT"),
    )
    assert decision.action is BrainAction.BLOCK
    assert decision.hard_constraint is True
    assert "DAILY_LOSS_LIMIT" in decision.reason


def test_valid_scalp_is_only_passed_down_for_risk_review():
    decision = TradingBrain().decide(
        market=BrainMarketState(
            symbol="ADAUSDT",
            signal="BUY",
            score=90,
            scalp_score=80,
            swing_score=60,
            macro_support=True,
            confirmed_reversal=True,
        ),
        risk=BrainRiskState(open_positions=1, max_open_positions=10, free_balance=900),
    )
    assert decision.action is BrainAction.ENTER
    assert decision.metadata["trade_mode"] == "SCALP"
    assert decision.executable is True


def test_incomplete_scalp_is_review_not_entry():
    decision = TradingBrain().decide(
        market=BrainMarketState(
            symbol="DOTUSDT",
            signal="BUY",
            scalp_score=75,
            macro_support=False,
            confirmed_reversal=False,
        ),
        risk=BrainRiskState(open_positions=1, max_open_positions=10),
    )
    assert decision.action is BrainAction.REVIEW
    assert decision.executable is False
