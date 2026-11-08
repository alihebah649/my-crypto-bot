from datetime import datetime, timezone

from core.paper_blocked_entry_shadow import (
    DEFAULT_MAX_BARS,
    advance_blocked_entry_watch,
    build_blocked_entry_watch,
)


def _capture():
    return {
        "capture_id": "blocked-capture-1",
        "captured_at": "2026-11-08T08:00:30+00:00",
        "symbol": "OPUSDT",
        "legacy_result": {
            "price": 100.0,
            "trade_mode": "SCALP",
            "scalp_score": 65,
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "risk": {
                "atr_stop_loss": 98.0,
                "target_price": 104.0,
                "target_source": "ATR_TARGET",
                "target_status": "VALID",
                "reward_risk": 2.0,
            },
        },
        "v2_decision": {
            "trade_mode": "SCALP",
            "failed_gate": "SELLER_PRESSURE_NOT_INVALIDATED",
        },
    }


def _bar(open_time, *, high, low, close, closed=True):
    return {
        "open_time": open_time,
        "close_time": open_time + 299999,
        "high": high,
        "low": low,
        "close": close,
        "is_closed": closed,
    }


def test_watch_uses_only_entry_time_capture_and_models_fees():
    watch = build_blocked_entry_watch(
        _capture(),
        fee_rate=0.001,
        blocked_reason="PAPER_TRIAL_MAIN_SCALP_SELLER_PRESSURE",
    )

    assert watch["status"] == "OBSERVING"
    assert watch["source_capture_id"] == "blocked-capture-1"
    assert watch["entry_price"] == 100.0
    assert watch["stop_price"] == 98.0
    assert watch["target_price"] == 104.0
    assert watch["estimated_round_trip_fee_percent"] == 0.2
    assert watch["path_model"] == "ENTRY_V2_ATR_STOP_AND_TARGET"
    assert watch["max_bars"] == DEFAULT_MAX_BARS


def test_watch_skips_pre_entry_and_open_candles_then_records_target_hit():
    watch = build_blocked_entry_watch(_capture(), fee_rate=0.001, blocked_reason="TRIAL")
    before = _bar(1794124800000, high=106, low=97, close=101)
    open_candle = _bar(1794125100000, high=106, low=97, close=101, closed=False)
    first = _bar(1794125100000, high=101, low=99, close=100)
    target = _bar(1794125400000, high=104, low=99, close=103)

    updated, changed = advance_blocked_entry_watch(watch, [before, open_candle, first, target])

    assert changed is True
    assert updated["status"] == "TARGET_HIT"
    assert updated["outcome_class"] == "TARGET"
    assert updated["bars_observed"] == 2
    assert updated["hypothetical_exit_price"] == 104.0
    assert updated["gross_return_percent"] == 4.0
    assert updated["net_return_percent_after_estimated_fees"] == 3.8
    assert updated["net_r_multiple_after_estimated_fees"] == 1.9


def test_watch_marks_same_candle_stop_and_target_as_ambiguous():
    watch = build_blocked_entry_watch(_capture(), fee_rate=0.001, blocked_reason="TRIAL")
    both = _bar(1794125100000, high=104.5, low=97.5, close=100)

    updated, changed = advance_blocked_entry_watch(watch, [both])

    assert changed is True
    assert updated["status"] == "AMBIGUOUS_SAME_CANDLE"
    assert updated["outcome_class"] == "AMBIGUOUS"
    assert updated["net_return_percent_after_estimated_fees"] is None


def test_watch_stops_at_stop_price_and_deducts_round_trip_fees():
    watch = build_blocked_entry_watch(_capture(), fee_rate=0.001, blocked_reason="TRIAL")
    stop = _bar(1794125100000, high=101, low=98, close=99)

    updated, _ = advance_blocked_entry_watch(watch, [stop])

    assert updated["status"] == "STOP_HIT"
    assert updated["hypothetical_exit_price"] == 98.0
    assert updated["gross_return_percent"] == -2.0
    assert updated["net_return_percent_after_estimated_fees"] == -2.2
    assert updated["net_r_multiple_after_estimated_fees"] == -1.1


def test_watch_marks_missing_candles_as_incomplete_not_as_a_loss():
    watch = build_blocked_entry_watch(_capture(), fee_rate=0.001, blocked_reason="TRIAL")
    gap = _bar(1794125700000, high=101, low=99, close=100)

    updated, changed = advance_blocked_entry_watch(watch, [gap])

    assert changed is True
    assert updated["status"] == "DATA_GAP"
    assert updated["outcome_class"] == "INCOMPLETE_DATA_GAP"
    assert updated["net_return_percent_after_estimated_fees"] is None


def test_watch_closes_at_the_predeclared_24_bar_horizon():
    watch = build_blocked_entry_watch(_capture(), fee_rate=0.001, blocked_reason="TRIAL")
    candles = [
        _bar(1794125100000 + index * 300000, high=101, low=99, close=100.5)
        for index in range(DEFAULT_MAX_BARS)
    ]

    updated, changed = advance_blocked_entry_watch(watch, candles)

    assert changed is True
    assert updated["status"] == "TIME_LIMIT_EXIT"
    assert updated["outcome_class"] == "TIME_EXIT"
    assert updated["bars_observed"] == DEFAULT_MAX_BARS
    assert updated["hypothetical_exit_price"] == 100.5
    assert updated["net_return_percent_after_estimated_fees"] == 0.3


def test_missing_entry_price_is_explicitly_unmeasurable():
    capture = _capture()
    capture["legacy_result"]["price"] = None

    watch = build_blocked_entry_watch(capture, fee_rate=0.001, blocked_reason="TRIAL")

    assert watch["status"] == "UNMEASURABLE_CONTEXT"
    assert watch["outcome_class"] == "UNMEASURABLE"
