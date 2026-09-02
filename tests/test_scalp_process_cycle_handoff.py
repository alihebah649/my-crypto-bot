from __future__ import annotations

import dual_mode_strategy
import shadow_main
from trade_manager.models import Position, PositionSide, PositionStatus


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def _position() -> Position:
    return Position(
        position_id="test-scalp-process-cycle",
        symbol="FETUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=96.0,
        take_profit=None,
    )


def test_process_cycle_generated_scalp_signal_reaches_runtime(monkeypatch):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 44.0)
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda data, period=20, deviations=2.0: (
            (100.0, 110.0, 121.0) if len(data) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda data, window=20: 1.20)
    monkeypatch.setattr(
        dual_mode_strategy,
        "bullish_pattern",
        lambda data: (True, "MORNING_STAR", False),
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "_scalp_recovery_confirmation",
        lambda data, current_rsi: (True, 2, ["5M_PRICE_RECOVERY", "5M_BULLISH_BODY"]),
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "analyze_multi_timeframe_context",
        lambda data: {
            "available": True,
            "bias": "NEUTRAL",
            "net": 0,
            "weighted_bull": 0,
            "weighted_bear": 0,
            "weak_countertrend_recovery": False,
            "aligned_bullish": False,
            "higher_timeframes_bearish": False,
            "higher_timeframes_bullish": False,
            "frames": {},
        },
    )

    ticker = {
        "lastPrice": "100.0",
        "bidPrice": "99.99",
        "askPrice": "100.01",
        "quoteVolume": "1000000.0",
    }
    strategy_data = ({"FETUSDT": ticker}, {"FETUSDT": candles(130)}, {"FETUSDT": candles(30)})
    monkeypatch.setattr(shadow_main._legacy, "fetch_strategy_data", lambda: strategy_data)
    monkeypatch.setattr(shadow_main._legacy, "fetch_klines", lambda symbol, interval, limit: candles(6))

    captured = {}
    position = _position()

    def fake_runtime_open_position(symbol, entry_price, stop_loss, trade_mode="SWING"):
        captured["symbol"] = symbol
        captured["trade_mode"] = trade_mode
        return position

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_runtime_open_position)
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda item: None)
    monkeypatch.setattr(shadow_main, "_original_send_telegram_message", lambda message: True)

    shadow_main._legacy.process_market_cycle()

    result = shadow_main._legacy.latest_scores["FETUSDT"]
    assert result["scalp_score"] == 68
    assert result["scalp_gate"] is True
    assert result["scalp_signal"] == "BUY"
    assert result["trade_mode"] == "SCALP"
    assert captured == {"symbol": "FETUSDT", "trade_mode": "SCALP"}
    assert shadow_main.runtime.last_entry_diagnostics["FETUSDT"]["trade_mode"] == "SCALP"
