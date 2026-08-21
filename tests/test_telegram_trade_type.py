"""Regression coverage for Telegram BUY trade-type labeling."""

import shadow_main


def test_buy_notification_includes_selected_scalp_trade_type(monkeypatch):
    shadow_main._legacy.latest_scores["BTCUSDT"] = {"trade_mode": "SCALP"}
    captured = []
    monkeypatch.setattr(shadow_main, "_original_send_telegram_message", lambda message: captured.append(message) or True)

    assert shadow_main._send_telegram_with_trade_type(
        "=== PAPER BUY ===\nSymbol: BTCUSDT\nScore: 70/100\nPAPER ONLY"
    ) is True
    assert "Trade Type: SCALP" in captured[0]


def test_buy_notification_includes_selected_swing_trade_type(monkeypatch):
    shadow_main._legacy.latest_scores["ETHUSDT"] = {"trade_mode": "SWING"}
    captured = []
    monkeypatch.setattr(shadow_main, "_original_send_telegram_message", lambda message: captured.append(message) or True)

    assert shadow_main._send_telegram_with_trade_type(
        "=== PAPER BUY ===\nSymbol: ETHUSDT\nScore: 80/100\nPAPER ONLY"
    ) is True
    assert "Trade Type: SWING" in captured[0]
