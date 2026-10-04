from __future__ import annotations

import shadow_main_base


def test_telegram_identity_header_is_mode_specific(monkeypatch):
    assert shadow_main_base._telegram_identity_header().startswith("🤖 BOT: MAIN BOT")
    assert "MIXED / 22-SYMBOL SHARDED" in shadow_main_base._telegram_identity_header()

    monkeypatch.setattr(shadow_main_base, "PAPER_VENUE_MODE", "BINANCE_ONLY_LAB")
    shadow_main_base._PAPER_BOT_IDENTITY = ("BINANCE LAB", "BINANCE ONLY / 22 SYMBOLS")
    assert shadow_main_base._telegram_identity_header() == (
        "🤖 BOT: BINANCE LAB\n🏷️ VENUE: BINANCE ONLY / 22 SYMBOLS"
    )

    monkeypatch.setattr(shadow_main_base, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB")
    shadow_main_base._PAPER_BOT_IDENTITY = ("BYBIT LAB", "BYBIT ONLY / 22 SYMBOLS")
    assert shadow_main_base._telegram_identity_header() == (
        "🤖 BOT: BYBIT LAB\n🏷️ VENUE: BYBIT ONLY / 22 SYMBOLS"
    )


def test_paper_buy_message_contains_bot_identity_and_trade_type(monkeypatch):
    sent = {}

    def capture(message):
        sent["message"] = message
        return True

    monkeypatch.setattr(shadow_main_base, "_original_send_telegram_message", capture)
    monkeypatch.setattr(
        shadow_main_base,
        "_PAPER_BOT_IDENTITY",
        ("BYBIT LAB", "BYBIT ONLY / 22 SYMBOLS"),
    )
    monkeypatch.setattr(shadow_main_base._legacy, "latest_scores", {
        "BTCUSDT": {
            "scalp_signal": "BUY",
            "swing_signal": "HOLD",
            "trade_mode": "SCALP",
        }
    })

    assert shadow_main_base._send_telegram_with_trade_type(
        "=== PAPER BUY ===\nSymbol: BTCUSDT\nPAPER ONLY"
    )

    message = sent["message"]
    assert message.startswith("🤖 BOT: BYBIT LAB\n🏷️ VENUE: BYBIT ONLY / 22 SYMBOLS\n")
    assert "Trade Type: SCALP" in message
    assert "PAPER ONLY" in message


def test_non_trade_telegram_message_also_contains_identity(monkeypatch):
    sent = {}

    def capture(message):
        sent["message"] = message
        return True

    monkeypatch.setattr(shadow_main_base, "_original_send_telegram_message", capture)
    monkeypatch.setattr(
        shadow_main_base,
        "_PAPER_BOT_IDENTITY",
        ("BINANCE LAB", "BINANCE ONLY / 22 SYMBOLS"),
    )

    assert shadow_main_base._send_telegram_with_trade_type("PAPER MARKET HEALTH\nPAPER ONLY")
    assert sent["message"].startswith(
        "🤖 BOT: BINANCE LAB\n🏷️ VENUE: BINANCE ONLY / 22 SYMBOLS\n"
    )
