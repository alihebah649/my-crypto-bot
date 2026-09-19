from core.brain_market_regime import derive_market_regime


def test_derives_bull_from_both_higher_timeframes():
    view = derive_market_regime({
        "mtf_timeframe_bias": {"1h": "BULLISH", "4h": "BULLISH"},
        "mtf_net": 4,
    })
    assert view.regime == "BULL"
    assert view.higher_timeframe_bullish is True
    assert view.higher_timeframe_bearish is False


def test_derives_bear_from_both_higher_timeframes():
    view = derive_market_regime({
        "mtf_timeframe_bias": {"1h": "BEARISH", "4h": "BEARISH"},
        "mtf_net": -6,
    })
    assert view.regime == "BEAR"
    assert view.higher_timeframe_bearish is True


def test_btc_crash_forces_bear_regime():
    view = derive_market_regime({
        "mtf_timeframe_bias": {"1h": "BULLISH", "4h": "BULLISH"},
        "mtf_net": 20,
    }, btc_crashing=True)
    assert view.regime == "BEAR"
    assert view.reason == "BTC_CRASH_GUARD"


def test_mixed_higher_timeframes_use_weighted_balance():
    view = derive_market_regime({
        "mtf_timeframe_bias": {"1h": "BEARISH", "4h": "BULLISH"},
        "mtf_weighted_bull": 40,
        "mtf_weighted_bear": 32,
        "mtf_net": 8,
    })
    assert view.regime == "BULL"
    assert view.higher_timeframe_bearish is False
    assert view.higher_timeframe_bullish is False
