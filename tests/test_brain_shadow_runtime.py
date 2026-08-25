from core.brain_shadow_runtime import BrainShadowRuntime


def test_shadow_runtime_does_not_change_strategy_decision():
    runtime = BrainShadowRuntime()
    strategy = {
        "signal": "BUY",
        "score": 66,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": False,
    }

    result = runtime.evaluate_entry("OPUSDT", strategy)

    assert result.strategy_action == "BUY"
    assert result.brain_action == "HOLD"
    assert result.agreement is False
    assert strategy["signal"] == "BUY"
    assert runtime.snapshot() == {"total": 1, "agreements": 0, "disagreements": 1}


def test_shadow_runtime_agrees_on_strong_confirmed_entry():
    runtime = BrainShadowRuntime()
    strategy = {
        "signal": "BUY",
        "score": 91,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
    }

    result = runtime.evaluate_entry("BTCUSDT", strategy)

    assert result.brain_action == "BUY"
    assert result.agreement is True
    assert runtime.snapshot() == {"total": 1, "agreements": 1, "disagreements": 0}


def test_shadow_runtime_risk_lock_blocks_brain_entry_but_not_strategy():
    runtime = BrainShadowRuntime()
    strategy = {
        "signal": "BUY",
        "score": 95,
        "trade_mode": "SWING",
        "scalp_confirmed_reversal": True,
    }

    result = runtime.evaluate_entry("ETHUSDT", strategy, risk_locked=True)

    assert result.strategy_action == "BUY"
    assert result.brain_action == "HOLD"
    assert result.agreement is False
