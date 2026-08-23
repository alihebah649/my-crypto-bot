from core.brain_market_context import BrainMarketContextAdapter


def test_market_context_normalizes_existing_fields_only():
    context = BrainMarketContextAdapter.build(
        market={"ema_100": "BULLISH", "atr_percent": 1.4, "unexpected": 123},
        strategy={"trend": "UP", "score": 8, "market_regime": "TRENDING"},
    )

    assert context == {
        "ema_100": "BULLISH",
        "atr_percent": 1.4,
        "trend": "UP",
        "market_regime": "TRENDING",
        "score": 8,
    }
    assert "unexpected" not in context


def test_market_context_does_not_mutate_inputs():
    market = {"ema": 100}
    strategy = {"score": 7}
    context = BrainMarketContextAdapter.build(market, strategy)

    context["ema"] = 200
    assert market["ema"] == 100
    assert strategy["score"] == 7
