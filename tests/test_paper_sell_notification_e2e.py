"""End-to-end Paper SELL notification reconciliation contract."""
from __future__ import annotations

import shadow_main
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_closed_paper_position_is_notified_after_real_trade_manager_close(monkeypatch, tmp_path):
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
    closed = runtime.facade.close_position(position.position_id, 0.19)
    assert closed is not None
    assert closed.status.name == "CLOSED"
    assert closed.exit_metadata.get("telegram_notification_sent") is None

    sent = []
    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(
        shadow_main._legacy,
        "send_telegram_message",
        lambda message: sent.append(message) or True,
    )

    assert shadow_main._notify_closed_positions() == 1
    assert len(sent) == 1
    assert "PAPER SELL" in sent[0]
    assert "ADAUSDT" in sent[0]
    assert "Net P&L:" in sent[0]
    assert closed.exit_metadata["telegram_notification_sent"] is True

    # Reconciliation is idempotent: the acknowledged SELL is never sent twice.
    assert shadow_main._notify_closed_positions() == 0
    assert len(sent) == 1
