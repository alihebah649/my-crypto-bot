from datetime import datetime, timezone

from core.paper_structural_stop_comparison import (
    advance_structural_stop_comparison,
    build_structural_stop_comparison_decision,
    build_structural_stop_comparison_report,
    build_structural_stop_comparison_watch,
)


def _capture():
    return {
        "capture_id": "entry-capture-structural-1",
        "captured_at": "2026-11-08T08:00:30+00:00",
        "symbol": "OPUSDT",
        "legacy_result": {
            "price": 100.0,
            "trade_mode": "SCALP",
            "scalp_score": 72,
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "risk": {
                "atr_stop_loss": 98.0,
                "structural_stop_candidate": 97.0,
                "structural_stop_source": "5m_PIVOT_LOW",
                "structural_stop_timeframe": "5m",
                "target_price": 104.0,
                "target_source": "PIVOT_HIGH",
                "target_status": "VALID",
                "reward_risk": 2.0,
            },
        },
    }


def _position(entry=100.0):
    return {
        "position_id": "POS-structural-1",
        "symbol": "OPUSDT",
        "entry_price": entry,
        "trade_mode": "SCALP",
        "status": "OPEN",
        "entry_metadata": {"trade_mode": "SCALP"},
    }


def _next_bar_open():
    captured_ms = int(
        datetime.fromisoformat(_capture()["captured_at"]).replace(tzinfo=timezone.utc).timestamp()
        * 1000
    )
    return (captured_ms // 300000 + 1) * 300000


def _bar(open_time, *, high, low, close, closed=True):
    return {
        "open_time": open_time,
        "close_time": open_time + 299999,
        "high": high,
        "low": low,
        "close": close,
        "is_closed": closed,
    }


def test_watch_freezes_both_entry_time_stops_and_reanchors_to_paper_fill():
    watch = build_structural_stop_comparison_watch(
        _capture(),
        _position(entry=100.5),
        fee_rate=0.001,
        venue="BINANCE",
        venue_mode="MIXED",
    )

    assert watch["status"] == "OBSERVING"
    assert watch["source_capture_id"] == "entry-capture-structural-1"
    assert watch["position_id"] == "POS-structural-1"
    assert watch["entry_price"] == 100.5
    assert watch["atr_path"]["stop_price"] == 98.5
    assert watch["structural_path"]["stop_price"] == 97.5
    assert watch["target_price"] == 104.5
    assert watch["structural_comparison"] == "STRUCTURAL_WIDER"
    assert watch["estimated_round_trip_fee_percent"] == 0.2
    assert watch["path_source"] == "BINANCE_CLOSED_5M_CANDLES"
    assert watch["mode"] == "PAPER_ONLY"
    assert watch["trading_logic_changed"] is False



def test_uses_actual_initial_paper_stop_when_present():
    position = _position()
    position["stop_loss"] = 98.25

    watch = build_structural_stop_comparison_watch(
        _capture(), position, fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )

    assert watch["atr_path"]["stop_price"] == 98.25
    assert watch["atr_stop_source"] == "PAPER_POSITION_INITIAL_STOP"
    assert watch["captured_atr_stop_price"] == 98.0


def test_unmeasurable_position_decision_is_explicit_and_paper_only():
    decision = build_structural_stop_comparison_decision(
        _position(),
        source_capture_id="entry-capture-structural-1",
        venue="BYBIT",
        venue_mode="BYBIT_ONLY_LAB",
        reason="STRUCTURAL_STOP_CANDIDATE_UNAVAILABLE",
    )

    assert decision["record_type"] == "DECISION"
    assert decision["position_id"] == "POS-structural-1"
    assert decision["reason"] == "STRUCTURAL_STOP_CANDIDATE_UNAVAILABLE"
    assert decision["mode"] == "PAPER_ONLY"
    assert decision["capture_id"] == "POS-structural-1:DECISION"



def test_same_closed_candles_compare_atr_stop_hit_against_structural_target_hit():
    watch = build_structural_stop_comparison_watch(
        _capture(), _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )
    first_open = _next_bar_open()
    bars = [
        _bar(first_open, high=101.0, low=97.5, close=99.0),
        _bar(first_open + 300000, high=104.5, low=98.0, close=104.0),
    ]

    updated, changed = advance_structural_stop_comparison(watch, bars)

    assert changed is True
    assert updated["status"] == "COMPLETE"
    assert updated["bars_observed"] == 2
    assert updated["atr_path"]["status"] == "STOP_HIT"
    assert updated["atr_path"]["hypothetical_exit_price"] == 98.0
    assert updated["atr_path"]["net_return_percent_after_estimated_fees"] == -2.2
    assert updated["structural_path"]["status"] == "TARGET_HIT"
    assert updated["structural_path"]["hypothetical_exit_price"] == 104.0
    assert updated["structural_path"]["net_return_percent_after_estimated_fees"] == 3.8


def test_same_bar_stop_and_target_is_ambiguous_for_that_path():
    watch = build_structural_stop_comparison_watch(
        _capture(), _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )
    updated, _ = advance_structural_stop_comparison(
        watch,
        [_bar(_next_bar_open(), high=104.5, low=96.5, close=100.0)],
    )

    assert updated["atr_path"]["status"] == "AMBIGUOUS_SAME_CANDLE"
    assert updated["structural_path"]["status"] == "AMBIGUOUS_SAME_CANDLE"
    assert updated["atr_path"]["net_return_percent_after_estimated_fees"] is None


def test_entry_candle_and_open_candles_are_never_used():
    watch = build_structural_stop_comparison_watch(
        _capture(), _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )
    entry_open = watch["last_processed_open_time_ms"]
    bars = [
        _bar(entry_open, high=110.0, low=90.0, close=100.0),
        _bar(_next_bar_open(), high=110.0, low=90.0, close=100.0, closed=False),
    ]

    updated, changed = advance_structural_stop_comparison(watch, bars)

    assert changed is False
    assert updated["bars_observed"] == 0
    assert updated["status"] == "OBSERVING"


def test_data_gap_is_incomplete_and_never_counted_as_a_loss():
    watch = build_structural_stop_comparison_watch(
        _capture(), _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )
    gap_open = _next_bar_open() + 600000
    updated, changed = advance_structural_stop_comparison(
        watch, [_bar(gap_open, high=101.0, low=99.0, close=100.0)]
    )

    assert changed is True
    assert updated["status"] == "COMPLETE"
    assert updated["atr_path"]["status"] == "DATA_GAP"
    assert updated["structural_path"]["status"] == "DATA_GAP"
    assert updated["atr_path"]["net_return_percent_after_estimated_fees"] is None


def test_time_limit_finishes_both_paths_at_the_same_closed_bar_close():
    watch = build_structural_stop_comparison_watch(
        _capture(),
        _position(),
        fee_rate=0.001,
        venue="BINANCE",
        venue_mode="MIXED",
        max_bars=2,
    )
    first_open = _next_bar_open()
    bars = [
        _bar(first_open, high=101.0, low=99.0, close=100.5),
        _bar(first_open + 300000, high=102.0, low=99.0, close=101.0),
    ]
    updated, _ = advance_structural_stop_comparison(watch, bars)

    assert updated["status"] == "COMPLETE"
    assert updated["atr_path"]["status"] == "TIME_LIMIT_EXIT"
    assert updated["structural_path"]["status"] == "TIME_LIMIT_EXIT"
    assert updated["atr_path"]["hypothetical_exit_price"] == 101.0
    assert updated["structural_path"]["hypothetical_exit_price"] == 101.0


def test_report_compares_only_paired_decisive_positions():
    watch = build_structural_stop_comparison_watch(
        _capture(), _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
    )
    first_open = _next_bar_open()
    final, _ = advance_structural_stop_comparison(
        watch,
        [
            _bar(first_open, high=101.0, low=97.5, close=99.0),
            _bar(first_open + 300000, high=104.5, low=98.0, close=104.0),
        ],
    )
    final["record_type"] = "FINAL"
    final["record_id"] = "POS-structural-1:FINAL"
    report = build_structural_stop_comparison_report([watch, final])

    assert report["coverage"]["unique_positions_started"] == 1
    assert report["coverage"]["positions_completed"] == 1
    assert report["comparison"]["paired_decisive_positions"] == 1
    assert report["comparison"]["structural_better"] == 1
    assert report["comparison"]["structural_worse"] == 0
    assert report["comparison"]["average_structural_minus_atr_net_return_percent"] == 6.0
    assert report["overall"]["atr"]["decisive_positions"] == 1
    assert report["overall"]["structural"]["decisive_positions"] == 1
    assert report["mode"] == "PAPER_ONLY"


def test_missing_structural_candidate_fails_closed():
    capture = _capture()
    capture["entry_scenario"]["risk"]["structural_stop_candidate"] = None

    try:
        build_structural_stop_comparison_watch(
            capture, _position(), fee_rate=0.001, venue="BINANCE", venue_mode="MIXED"
        )
    except ValueError as exc:
        assert str(exc) == "STRUCTURAL_STOP_CANDIDATE_UNAVAILABLE"
    else:
        raise AssertionError("missing structural candidate must not create a watch")
