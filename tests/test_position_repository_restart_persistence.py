from __future__ import annotations

from pathlib import Path

import pytest

from trade_manager.models import Position, PositionCloseReason, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


def make_position(quantity: float = 2.0) -> Position:
    return Position(
        position_id="POS-RESTART-001",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=quantity,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=96.0,
        take_profit=110.0,
        client_order_id="CLIENT-001",
        close_reason=PositionCloseReason.NONE,
    )


def test_open_position_survives_repository_restart(tmp_path: Path):
    path = tmp_path / "positions.json"
    first = PositionRepository(str(path))
    position = make_position()
    first.add(position)

    restarted = PositionRepository(str(path))
    restored = restarted.get(position.position_id)

    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity == pytest.approx(2.0)
    assert restored.symbol == "BTCUSDT"
    assert restored.client_order_id == "CLIENT-001"
    assert restarted.get_open_positions()[0].position_id == position.position_id


def test_failed_sell_state_survives_repository_restart(tmp_path: Path):
    path = tmp_path / "positions.json"
    first = PositionRepository(str(path))
    position = make_position()
    first.add(position)

    restarted = PositionRepository(str(path))
    restored = restarted.get(position.position_id)

    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity == pytest.approx(2.0)
    assert restored.closed_at is None
    assert restored.realized_pnl == pytest.approx(0.0)


def test_partial_position_remaining_quantity_survives_restart(tmp_path: Path):
    path = tmp_path / "positions.json"
    first = PositionRepository(str(path))
    position = make_position(quantity=1.25)
    position.current_price = 110.0
    position.exit_metadata = {
        "partial_exit_quantity": 0.75,
        "partial_exit_price": 110.0,
        "execution_order_id": "PARTIAL-001",
    }
    first.add(position)

    restarted = PositionRepository(str(path))
    restored = restarted.get(position.position_id)

    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity == pytest.approx(1.25)
    assert restored.exit_metadata["partial_exit_quantity"] == pytest.approx(0.75)
    assert restarted.get_open_positions()[0].quantity == pytest.approx(1.25)
