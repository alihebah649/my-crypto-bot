from core.brain_models import BrainMarketState, BrainPosition, BrainRiskState, BrainAction
from core.brain_observer import BrainObserver


def test_observer_evaluates_existing_market_and_position_state_without_execution():
    batch = BrainObserver().evaluate(
        markets=[
            BrainMarketState(
                symbol="BTCUSDT",
                signal="HOLD",
            ),
            BrainMarketState(
                symbol="ADAUSDT",
                signal="BUY",
                scalp_score=80,
                macro_support=True,
                confirmed_reversal=True,
            ),
        ],
        risk=BrainRiskState(open_positions=1, max_open_positions=10),
        positions=[BrainPosition(symbol="BTCUSDT", hard_stop=True)],
    )

    assert len(batch.decisions) == 2
    assert batch.decisions[0].action is BrainAction.EXIT
    assert batch.decisions[1].action is BrainAction.ENTER
    assert all(decision.source == "deterministic_brain" for decision in batch.decisions)
