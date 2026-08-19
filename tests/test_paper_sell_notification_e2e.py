"""End-to-end Paper SELL notification reconciliation contract."""
from __future__ import annotations

import shadow_main
from trade_manager.models import PositionCloseReason
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_real_paper_sell_close_notification_is_complete_idempotent_and_retryable(
    monkeypatch, tmp_path
):
    """Exercise the real Paper lifecycle without bypassing Trade Manager.

    Contract covered here:
    BUY -> real Trade Manager close -> CLOSED position -> Telegram SELL
    acknowledgement -> persisted sent marker -> idempotent reconciliation.
    A first Telegram failure must leave the marker unset so the next
    reconciliation retries the same already-CLOSED position.
    """
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )
    runtime.update_market(
        "ADAUSDT",
        price=0.20,
        bid=0.1999,
        ask=0.2001,
        spread_percent=0.1,
        atr=0.004,
        volume_usdt=1_000_000.0,
        volatility=0.02,
        ema100=0.18,
    )

    position = runtime.open_position("ADAUSDT", 0.20, 0.196)
    assert position is not None
    assert position.status.name == "OPEN"

    runtime.update_market(
        "ADAUSDT",
        price=0.19,
        bid=0.1899,
        ask=0.1901,
        spread_percent=0.1,
        atr=0.004,
        volume_usdt=1_000_000.0,
        volatility=0.02,
        ema100=0.18,
    )
    closed = runtime.facade.close_position(
        position.position_id,
        0.19,
        PositionCloseReason.STOP_LOSS,
    )
    assert closed is not None
    assert closed.status.name == "CLOSED"
    assert closed.close_reason is PositionCloseReason.STOP_LOSS
    assert closed.exit_metadata.get("exit_price") == 0.19
    assert closed.exit_metadata.get("telegram_notification_sent") is None
    assert closed.realized_pnl < 0

    sent_messages = []
    delivery_results = iter([False, True])
    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(
        shadow_main._legacy,
        "send_telegram_message",
        lambda message: sent_messages.append(message) or next(delivery_results),
    )

    # First Telegram delivery fails: the trade remains CLOSED and the
    # notification marker must NOT be persisted as sent.
    assert shadow_main._notify_closed_positions() == 0
    assert len(sent_messages) == 1
    assert closed.status.name == "CLOSED"
    assert "telegram_notification_sent" not in closed.exit_metadata

    # The next reconciliation retries the same closed position and succeeds.
    assert shadow_main._notify_closed_positions() == 1
    assert len(sent_messages) == 2
    message = sent_messages[1]

    # Validate the actual SELL payload, not merely that Telegram was called.
    assert "PAPER SELL" in message
    assert "Symbol: ADAUSDT" in message
    assert "Reason: STOP_LOSS" in message
    assert "Gross P&L:" in message
    assert "Fees:" in message
    assert "Net P&L:" in message
    assert "P&L %:" in message
    assert "Paper cash:" in message
    assert "PAPER ONLY" in message
    assert closed.exit_metadata["telegram_notification_sent"] is True

    # Acknowledged notifications are idempotent: no third Telegram message.
    assert shadow_main._notify_closed_positions() == 0
    assert len(sent_messages) == 2
