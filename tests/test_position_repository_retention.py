from __future__ import annotations

import time

from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


def _position(position_id: str, status: PositionStatus, closed_at: float) -> Position:
    now = time.time()
    return Position(
        position_id=position_id,
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=status,
        quantity=0.01,
        entry_price=50_000.0,
        current_price=50_000.0,
        stop_loss=49_000.0,
        take_profit=52_000.0,
        opened_at=now - 60.0 * 24.0 * 60.0 * 60.0,
        closed_at=closed_at,
        metadata={},
        entry_metadata={},
    )


def test_prune_terminal_positions_keeps_active_recent_and_unpersisted_closed():
    now = time.time()
    cutoff = now - 40.0 * 24.0 * 60.0 * 60.0
    repo = PositionRepository()

    old_closed = _position("old-closed-persisted", PositionStatus.CLOSED, cutoff - 10.0)
    recent_closed = _position("recent-closed", PositionStatus.CLOSED, now - 3.0 * 86400.0)
    old_unpersisted = _position("old-closed-unpersisted", PositionStatus.CLOSED, cutoff - 20.0)
    old_cancelled = _position("old-cancelled", PositionStatus.CANCELLED, cutoff - 30.0)
    old_failed = _position("old-failed", PositionStatus.FAILED, cutoff - 40.0)
    active = _position("active", PositionStatus.OPEN, 0.0)

    for position in (
        old_closed,
        recent_closed,
        old_unpersisted,
        old_cancelled,
        old_failed,
        active,
    ):
        repo.add(position)

    removed = repo.prune_terminal_positions(
        older_than_epoch=cutoff,
        persisted_closed_ids={"old-closed-persisted"},
    )

    assert set(removed) == {
        "old-closed-persisted",
        "old-cancelled",
        "old-failed",
    }
    assert repo.get("old-closed-persisted") is None
    assert repo.get("old-cancelled") is None
    assert repo.get("old-failed") is None
    assert repo.get("recent-closed") is recent_closed
    assert repo.get("old-closed-unpersisted") is old_unpersisted
    assert repo.get("active") is active
