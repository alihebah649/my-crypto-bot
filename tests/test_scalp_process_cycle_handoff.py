from __future__ import annotations

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
    synthetic_score = {
        "symbol": "FETUSDT",
        "price": 100.0,
        "atr": 2.0,
        "score": 68,
        "scalp_score": 68,
        "scalp_gate": True,
        "scalp_signal": "BUY",
        "swing_score": 0,
        "swing_signal": "HOLD",
        "trade_mode": "SCALP",
        "signal": "BUY",
        "rsi": 44.0,
        "ema100": 99.0,
        "reasons": ["TEST_SCALP_SIGNAL"],
    }

    strategy_data = (
        {"FETUSDT": {"lastPrice": "100.0", "bidPrice": "99.99", "askPrice": "100.01", "quoteVolume": "1000000.0"}},
        {"FETUSDT": candles(130)},
        {"FETUSDT": candles(30)},
    )
    monkeypatch.setattr(shadow_main._legacy, "fetch_strategy_data", lambda: strategy_data)
    monkeypatch.setattr(
        shadow_main._legacy,
        "score_symbol",
        lambda symbol, ticker, candles_15m, candles_5m: dict(synthetic_score),
    )
    monkeypatch.setattr(shadow_main._legacy, "fetch_klines", lambda symbol, interval, limit: candles(6))

    captured = {}
    position = _position()

    def fake_runtime_open_position(symbol, entry_price, stop_loss, trade_mode="SWING"):
        captured["symbol"] = symbol
        captured["trade_mode"] = trade_mode
        return position

    # Test the actual orchestration handoff. Patching runtime.open_position
    # avoids coupling this test to internal wrappers captured during module
    # import and lets the assertion answer the intended question directly:
    # did a generated SCALP BUY reach runtime?
    monkeypatch.setattr(shadow_main.runtime, "open_position", fake_runtime_open_position)
    monkeypatch.setattr(shadow_main.runtime.controller, "has_position", lambda symbol: False)
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda item: None)
    monkeypatch.setattr(shadow_main, "_active_trade_modes", lambda symbol: set())
    monkeypatch.setattr(shadow_main, "_original_send_telegram_message", lambda message: True)

    shadow_main._legacy.process_market_cycle()

    result = shadow_main._legacy.latest_scores["FETUSDT"]
    assert result["scalp_score"] == 68
    assert result["scalp_gate"] is True
    assert result["scalp_signal"] == "BUY"
    assert result["trade_mode"] == "SCALP"
    assert captured == {"symbol": "FETUSDT", "trade_mode": "SCALP"}
    assert shadow_main.runtime.last_entry_diagnostics["FETUSDT"]["trade_mode"] == "SCALP"
