from core.brain_shadow_aggregator import aggregate_shadow_outcomes
from core.brain_shadow_outcome import BrainShadowOutcome


def outcome(action, horizon, return_percent, favorable):
    return BrainShadowOutcome(
        context_fingerprint="fp",
        symbol="BTCUSDT",
        action=action,
        horizon=horizon,
        entry_price=100.0,
        outcome_price=100.0 + return_percent,
        return_percent=return_percent,
        favorable=favorable,
    )


def test_aggregator_groups_by_action_and_horizon():
    metrics = aggregate_shadow_outcomes([
        outcome("BUY", "15m", 2.0, True),
        outcome("BUY", "15m", -1.0, False),
        outcome("HOLD", "15m", 0.5, True),
    ])

    buy = next(item for item in metrics if item.action == "BUY")
    assert buy.horizon == "15m"
    assert buy.sample_size == 2
    assert buy.favorable_count == 1
    assert buy.win_rate == 0.5
    assert buy.average_return_percent == 0.5


def test_empty_outcomes_return_no_metrics():
    assert aggregate_shadow_outcomes([]) == []
