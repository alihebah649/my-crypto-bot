import sys
from types import SimpleNamespace

from trade_manager.history import PositionHistoryRepository, PositionHistoryService
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


class _Repo:
    def __init__(self):
        self.updated = []

    def update(self, position):
        self.updated.append(position)


class _Portfolio:
    def snapshot(self):
        return SimpleNamespace(account_equity=1000.0, free_margin=900.0, open_positions=0)


class _Approval:
    approved = True
    reason = "APPROVED"
    quantity = 0.5
    position_value = 50.0
    capital_required = 50.0
    metadata = {"source": "TEST"}


class _RiskGateway:
    def approve(self, request):
        return _Approval()


class _Facade:
    last_entry_diagnostic = {"result": "POSITION_COMMITTED", "execution_gateway": "PASS"}

    def open_position(self, **kwargs):
        return Position(
            position_id="POS-entry-context",
            symbol=kwargs["symbol"],
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=0.5,
            entry_price=101.25,
            current_price=101.25,
            stop_loss=99.75,
            take_profit=None,
            entry_metadata=dict(kwargs["entry_metadata"]),
        )


def _runtime_for_capture():
    runtime = ShadowTradeManagerRuntime.__new__(ShadowTradeManagerRuntime)
    runtime.last_entry_diagnostics = {}
    runtime.risk_config = SimpleNamespace(
        position_sizing=SimpleNamespace(target_position_value=50.0, risk_per_trade_percent=1.0),
        exposure=SimpleNamespace(max_portfolio_exposure_percent=80.0),
    )
    runtime.portfolio_provider = _Portfolio()
    runtime.risk_gateway = _RiskGateway()
    runtime.facade = _Facade()
    runtime.repository = _Repo()
    return runtime


def _strategy_score():
    return {
        "symbol": "OPUSDT",
        "score": 77,
        "trade_mode": "SCALP",
        "scalp_score": 77,
        "swing_score": 61,
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
        "reasons": ["15M_BOLLINGER_NEAR_SUPPORT", "5M_BULLISH_ENGULFING_CONFIRMED"],
        "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT", "5M_BULLISH_ENGULFING_CONFIRMED"],
        "swing_reasons": [],
        "scalp_gate": True,
        "scalp_gate_reasons": ["CONFIRMED_5M_REVERSAL"],
        "rsi5m": 41.2,
        "rsi": 47.8,
        "volume_ratio_5m": 1.21,
        "volume_ratio": 1.08,
        "atr": 0.12,
        "atr5m": 0.04,
        "lower_band": 0.0,
        "middle_band": 0.0,
        "upper_band": 0.0,
        "lower_band_5m": 0.0,
        "middle_band_5m": 0.0,
        "upper_band_5m": 0.0,
        "pattern": "BULLISH_ENGULFING",
        "pattern_confirmed": True,
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": False,
        "scalp_recovery_trigger_count": 0,
        "scalp_recovery_trigger_reasons": [],
        "scalp_high_confidence_recovery": False,
        "scalp_context_only": False,
        "mtf_context_available": True,
        "mtf_bias": "NEUTRAL",
        "mtf_net": 0,
        "mtf_weighted_bull": 4,
        "mtf_weighted_bear": 4,
        "mtf_higher_timeframes_bearish": False,
        "mtf_higher_timeframes_bullish": False,
        "mtf_countertrend_warning": False,
        "mtf_countertrend_veto": False,
        "mtf_aligned_bullish": False,
        "mtf_timeframe_bias": {"1h": "NEUTRAL", "4h": "NEUTRAL"},
        "mtf_timeframe_strength": {"1h": 2, "4h": 2},
        "mtf_patterns": {"1h": [], "4h": []},
    }


def test_filled_position_captures_strategy_entry_context_and_history_persists_it(tmp_path):
    fake_entrypoint = SimpleNamespace(latest_scores={"OPUSDT": _strategy_score()})
    previous = sys.modules.get("shadow_main")
    sys.modules["shadow_main"] = fake_entrypoint
    try:
        runtime = _runtime_for_capture()
        position = runtime.open_position("OPUSDT", 101.0, 99.5, "SCALP")

        assert position is not None
        assert position.entry_metadata["trade_mode"] == "SCALP"
        context = position.entry_metadata["entry_context"]
        assert context["schema_version"] == 1
        assert context["strategy_context_available"] is True
        assert context["score"] == 77
        assert context["scalp_score"] == 77
        assert context["swing_score"] == 61
        assert context["rsi5m"] == 41.2
        assert context["volume_ratio_5m"] == 1.21
        assert context["pattern_confirmed"] is True
        assert context["scalp_confirmed_reversal"] is True
        assert context["mtf_timeframe_bias"]["1h"] == "NEUTRAL"
        assert context["filled_entry_price"] == 101.25
        assert context["stop_distance_percent"] > 0
        assert runtime.repository.updated[-1].entry_context == context

        history_repository = PositionHistoryRepository(str(tmp_path / "position_history.json"))
        history = PositionHistoryService(repository=history_repository)
        position.status = PositionStatus.CLOSED
        position.closed_at = position.opened_at + 60.0
        position.current_price = 99.0
        position.realized_pnl = -1.25
        position.gross_pnl = -1.15
        position.total_fees = 0.10
        history.record_closed_position(position)

        reloaded = PositionHistoryService(
            repository=PositionHistoryRepository(str(tmp_path / "position_history.json"))
        ).get_all_closed_positions()[0]
        assert reloaded.entry_metadata["entry_context"]["score"] == 77
        assert reloaded.entry_metadata["entry_context"]["rsi5m"] == 41.2
        assert reloaded.entry_metadata["entry_context"]["volume_ratio_5m"] == 1.21
    finally:
        if previous is None:
            sys.modules.pop("shadow_main", None)
        else:
            sys.modules["shadow_main"] = previous


def test_filled_position_uses_supplied_candidate_snapshot_not_later_latest_score():
    fake_entrypoint = SimpleNamespace(latest_scores={"OPUSDT": _strategy_score()})
    previous = sys.modules.get("shadow_main")
    sys.modules["shadow_main"] = fake_entrypoint
    try:
        runtime = _runtime_for_capture()
        later_score = _strategy_score()
        later_score["score"] = 93
        later_score["scalp_score"] = 93
        later_score["rsi5m"] = 28.5
        later_score["volume_ratio_5m"] = 2.75
        position = runtime.open_position(
            "OPUSDT",
            101.0,
            99.5,
            "SCALP",
            strategy_snapshot=later_score,
            strategy_snapshot_captured_at=1234.5,
        )

        context = position.entry_metadata["entry_context"]
        assert context["strategy_snapshot_source"] == "CANDIDATE_CAPTURE"
        assert context["strategy_snapshot_captured_at"] == 1234.5
        assert context["score"] == 93
        assert context["rsi5m"] == 28.5
        assert context["volume_ratio_5m"] == 2.75
    finally:
        if previous is None:
            sys.modules.pop("shadow_main", None)
        else:
            sys.modules["shadow_main"] = previous
