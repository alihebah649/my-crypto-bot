"""Integration regression for paper loss re-entry protection."""
from __future__ import annotations

from types import SimpleNamespace

from core.paper_risk_overlay import REENTRY_COOLDOWN_SECONDS, loss_cooldown_remaining


def test_closed_loss_blocks_same_symbol_before_cooldown_expires():
    closed = [
        SimpleNamespace(
            symbol="DOTUSDT",
            realized_pnl=-1.5471,
            closed_at=10_000.0,
        )
    ]

    assert loss_cooldown_remaining(
        closed,
        "DOTUSDT",
        now=10_540.0,
        cooldown_seconds=REENTRY_COOLDOWN_SECONDS,
    ) > 0


def test_closed_loss_allows_same_symbol_after_two_hours():
    closed = [
        SimpleNamespace(
            symbol="DOTUSDT",
            realized_pnl=-1.5471,
            closed_at=10_000.0,
        )
    ]

    assert loss_cooldown_remaining(
        closed,
        "DOTUSDT",
        now=10_000.0 + REENTRY_COOLDOWN_SECONDS + 1.0,
        cooldown_seconds=REENTRY_COOLDOWN_SECONDS,
    ) == 0.0


def test_loss_cooldown_is_symbol_specific():
    closed = [
        SimpleNamespace(
            symbol="DOTUSDT",
            realized_pnl=-1.5471,
            closed_at=10_000.0,
        )
    ]

    assert loss_cooldown_remaining(
        closed,
        "ARBUSDT",
        now=10_540.0,
        cooldown_seconds=REENTRY_COOLDOWN_SECONDS,
    ) == 0.0
