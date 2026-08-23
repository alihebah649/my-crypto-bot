from core.brain_shadow_outcome import BrainShadowOutcome
from core.brain_vs_deterministic import compare_realized_outcomes


def outcome(fp, action, horizon, ret, favorable):
    return BrainShadowOutcome(fp, "BTCUSDT", action, horizon, 100.0, 100.0, ret, favorable)


def test_compares_only_paired_contexts_and_counts_wins():
    ai = [outcome("a", "HOLD", "15m", 2.0, True), outcome("b", "HOLD", "15m", -1.0, False)]
    det = [outcome("a", "HOLD", "15m", 1.0, True), outcome("b", "HOLD", "15m", -2.0, False), outcome("unpaired", "HOLD", "15m", 9.0, True)]
    result = compare_realized_outcomes(ai, det)
    metric = result[0]
    assert metric.sample_size == 2
    assert metric.ai_win_rate == 0.5
    assert metric.deterministic_win_rate == 0.5
    assert metric.ai_average_return_percent == 0.5
    assert metric.deterministic_average_return_percent == -0.5
    assert metric.ai_better_count == 2
    assert metric.deterministic_better_count == 0
    assert metric.tie_count == 0


def test_no_paired_outcomes_produce_no_metrics():
    assert compare_realized_outcomes([outcome("a", "BUY", "1h", 1.0, True)], []) == []
