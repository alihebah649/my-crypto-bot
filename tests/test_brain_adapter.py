from types import SimpleNamespace

from core.brain_adapter import market_from_score, position_from_runtime


def test_market_adapter_preserves_existing_strategy_evidence():
    state = market_from_score(
        "ADAUSDT",
        {
            "signal": "BUY",
            "score": 80,
            "scalp_score": 80,
            "swing_score": 60,
            "trade_mode": "SCALP",
            "scalp_gate": True,
            "scalp_confirmed_reversal": True,
            "volume_ratio_5m": 1.4,
            "rsi5m": 31.0,
            "pattern": "HAMMER",
            "pattern_confirmed": True,
            "scalp_gate_reasons": ["CONFIRMED_5M_REVERSAL"],
            "reasons": ["15M_BOLLINGER_NEAR_SUPPORT"],
        },
    )
    assert state.signal == "BUY"
    assert state.scalp_score == 80
    assert state.confirmed_reversal is True
    assert state.volume_ratio_5m == 1.4
    assert state.metadata["trade_mode"] == "SCALP"


def test_position_adapter_is_read_only_mapping_of_exit_state():
    position = SimpleNamespace(
        symbol="BTCUSDT",
        entry_metadata={"trade_mode": "SCALP"},
        exit_metadata={"hard_stop_triggered": False, "scalp_timeout": True, "exit_candidate": True},
        metadata={"age_minutes": 47},
        gross_pnl=0.5,
        entry_price=100.0,
        quantity=1.0,
        status=SimpleNamespace(name="OPEN"),
    )
    state = position_from_runtime(position)
    assert state.symbol == "BTCUSDT"
    assert state.trade_mode == "SCALP"
    assert state.age_minutes == 47
    assert state.timeout is True
    assert state.exit_candidate is True
