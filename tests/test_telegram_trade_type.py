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



def test_hosted_lab_buy_preserves_its_own_trade_type(monkeypatch):
    # MAIN's current mode may differ from the isolated lab's executed mode.
    shadow_main._legacy.latest_scores["DOTUSDT"] = {
        "trade_mode": "SCALP",
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
    }
    captured = []
    monkeypatch.setattr(
        shadow_main,
        "_original_send_telegram_message",
        lambda message: captured.append(message) or True,
    )

    message = (
        "🤖 BOT: BYBIT PAPER LAB\\n"
        "🏷️ VENUE: BYBIT SPOT ONLY\\n"
        "=== PAPER BUY ===\\n"
        "Symbol: DOTUSDT\\n"
        "Trade Type: SWING\\n"
        "Score: 88/100\\n"
        "PAPER ONLY"
    )
    assert shadow_main._send_telegram_with_trade_type(message) is True
    assert captured[0].count("Trade Type:") == 1
    assert "Trade Type: SWING" in captured[0]
    assert "Trade Type: SCALP" not in captured[0]
