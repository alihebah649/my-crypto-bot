"""Paper SELL notification reconciliation tests."""

from types import SimpleNamespace

import shadow_main


class _FakeRepository:
    def __init__(self, positions):
        self.positions = positions
        self.updated = []

    def get_closed_positions(self):
        return list(self.positions)

    def update(self, position):
        self.updated.append(position)


def _closed_position():
    return SimpleNamespace(
        symbol="ADAUSDT",
        quantity=0.5,
        entry_price=0.20,
        current_price=0.19,
        close_reason=SimpleNamespace(name="STOP_LOSS"),
        gross_pnl=-0.005,
        total_fees=0.000195,
        realized_pnl=-0.005195,
        exit_metadata={"exit_price": 0.19},
    )


def test_closed_paper_position_gets_sell_notification_once(monkeypatch):
    position = _closed_position()
    repository = _FakeRepository([position])
    fake_runtime = SimpleNamespace(
        repository=repository,
        execution_adapter=SimpleNamespace(balance=SimpleNamespace(cash=949.90)),
    )
    sent_messages = []

    monkeypatch.setattr(shadow_main, "runtime", fake_runtime)
    monkeypatch.setattr(shadow_main._legacy, "send_telegram_message", lambda message: sent_messages.append(message) or True)

    assert shadow_main._notify_closed_positions() == 1
    assert len(sent_messages) == 1
    assert "PAPER SELL" in sent_messages[0]
    assert "ADAUSDT" in sent_messages[0]
    assert "Net P&L: -0.0052$" in sent_messages[0]
    assert position.exit_metadata["telegram_notification_sent"] is True
    assert repository.updated == [position]

    assert shadow_main._notify_closed_positions() == 0
    assert len(sent_messages) == 1


def test_failed_telegram_delivery_is_retried(monkeypatch):
    position = _closed_position()
    repository = _FakeRepository([position])
    fake_runtime = SimpleNamespace(
        repository=repository,
        execution_adapter=SimpleNamespace(balance=SimpleNamespace(cash=949.90)),
    )
    outcomes = iter([False, True])
    sent_messages = []

    monkeypatch.setattr(shadow_main, "runtime", fake_runtime)
    monkeypatch.setattr(shadow_main._legacy, "send_telegram_message", lambda message: sent_messages.append(message) or next(outcomes))

    assert shadow_main._notify_closed_positions() == 0
    assert "telegram_notification_sent" not in position.exit_metadata
    assert shadow_main._notify_closed_positions() == 1
    assert position.exit_metadata["telegram_notification_sent"] is True
    assert len(sent_messages) == 2
