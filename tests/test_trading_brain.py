from brain.models import BrainAction, BrainInput, BrainSafetyState
from brain.orchestrator import TradingBrain


def test_hard_exit_has_priority_over_advisor():
    context = BrainInput(
        symbol="BTCUSDT",
        signal={"signal": "HOLD", "trade_mode": "SCALP"},
        safety=BrainSafetyState(hard_exit_required=True),
    )

    decision = TradingBrain().decide(context)

    assert decision.action is BrainAction.CLOSE
    assert decision.reason == "HARD_EXIT_REQUIRED"
    assert decision.confidence == 1.0


def test_risk_lock_blocks_new_entry_but_does_not_create_exit():
    context = BrainInput(
        symbol="ETHUSDT",
        signal={"signal": "BUY", "trade_mode": "SCALP", "score": 95},
        safety=BrainSafetyState(risk_locked=True),
    )

    decision = TradingBrain().decide(context)

    assert decision.action is BrainAction.BLOCK
    assert decision.reason == "RISK_LOCKED"


def test_risk_lock_does_not_block_management_of_existing_position():
    context = BrainInput(
        symbol="SOLUSDT",
        signal={"signal": "BUY", "trade_mode": "SCALP", "score": 95},
        position={"status": "OPEN"},
        safety=BrainSafetyState(risk_locked=True),
    )

    decision = TradingBrain().decide(context)

    assert decision.action is BrainAction.HOLD
    assert decision.reason == "OPEN_POSITION_REQUIRES_POSITION_MANAGEMENT"


def test_execution_unavailable_downgrades_entry_to_review():
    context = BrainInput(
        symbol="ADAUSDT",
        signal={"signal": "BUY", "trade_mode": "SCALP", "score": 90},
        safety=BrainSafetyState(execution_available=False),
    )

    decision = TradingBrain().decide(context)

    assert decision.action is BrainAction.REVIEW
    assert decision.reason == "EXECUTION_UNAVAILABLE"


def test_rule_advisor_can_propose_scalp_entry_without_executing_it():
    context = BrainInput(
        symbol="BNBUSDT",
        signal={"signal": "BUY", "trade_mode": "SCALP", "score": 85},
    )

    decision = TradingBrain().decide(context)

    assert decision.action is BrainAction.OPEN
    assert decision.mode == "SCALP"
    assert decision.confidence == 0.85
