"""Explicit adapter between the core Position model and Trade Manager Position.

The project currently has two legitimate domain models with different
responsibilities. This module is the only supported conversion boundary; no
caller should rely on duck-typing or duplicate persistence for the two models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models import Position as CorePosition
from core.models import PositionStatus as CorePositionStatus
from core.models import RecoveryState

from .models import Position as TradeManagerPosition
from .models import PositionCloseReason, PositionSide, PositionStatus


_CORE_TO_TM_STATUS = {
    CorePositionStatus.OPEN: PositionStatus.OPEN,
    CorePositionStatus.CLOSED: PositionStatus.CLOSED,
    CorePositionStatus.RECOVERY: PositionStatus.HOLD,
    CorePositionStatus.PAUSED: PositionStatus.REVIEW_REQUIRED,
}

_TM_TO_CORE_STATUS = {
    PositionStatus.CREATED: CorePositionStatus.OPEN,
    PositionStatus.OPEN: CorePositionStatus.OPEN,
    PositionStatus.PARTIALLY_CLOSED: CorePositionStatus.OPEN,
    PositionStatus.HOLD: CorePositionStatus.RECOVERY,
    PositionStatus.REVIEW_REQUIRED: CorePositionStatus.PAUSED,
    PositionStatus.CLOSED: CorePositionStatus.CLOSED,
    PositionStatus.CANCELLED: CorePositionStatus.CLOSED,
    PositionStatus.FAILED: CorePositionStatus.PAUSED,
}


def core_to_trade_manager(position: CorePosition) -> TradeManagerPosition:
    """Convert a core position into the canonical TM lifecycle model."""
    opened_at = position.entry_time.timestamp()
    return TradeManagerPosition(
        position_id=position.trade_id or f"CORE-{position.symbol}-{int(opened_at * 1000)}",
        symbol=position.symbol,
        side=PositionSide.LONG,
        status=_CORE_TO_TM_STATUS[position.status],
        quantity=position.runtime.remaining_quantity or position.quantity,
        entry_price=position.runtime.average_entry_price or position.entry_price,
        current_price=position.runtime.last_price or position.entry_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit or None,
        highest_price=position.runtime.highest_price_seen or position.highest_price or position.entry_price,
        max_profit_percent=position.runtime.highest_profit_percent,
        max_drawdown_percent=max(0.0, -position.runtime.lowest_profit_percent),
        recovery_active=position.recovery_state == RecoveryState.ACTIVE,
        partial_closed=position.partial_exit_done,
        opened_at=opened_at,
        close_reason=_close_reason(position.exit_reason),
        gross_pnl=position.realized_profit + position.unrealized_profit,
        realized_pnl=position.realized_profit,
        total_fees=position.fees_paid,
        entry_metadata={"core_trade_id": position.trade_id, "strategy_name": position.strategy_name},
        entry_context={"trade_type": position.trade_type.value, "strategy_version": position.strategy_version},
        metadata={
            "source_model": "core.models.Position",
            "recovery_state": position.recovery_state.value,
            "recovery_target_price": position.recovery_target_price,
        },
    )


def trade_manager_to_core(position: TradeManagerPosition, existing: CorePosition | None = None) -> CorePosition:
    """Project TM lifecycle state back into the core model.

    If an existing core position is supplied, its strategy/context fields are
    retained. This prevents the adapter from silently destroying core metadata.
    """
    now = datetime.now(timezone.utc)
    core = existing or CorePosition(
        symbol=position.symbol,
        quantity=position.quantity,
        entry_price=position.entry_price,
        trade_id=position.position_id,
    )
    core.symbol = position.symbol
    core.quantity = position.quantity
    core.entry_price = position.entry_price
    core.highest_price = position.highest_price
    core.stop_loss = position.stop_loss
    core.take_profit = position.take_profit or 0.0
    core.trade_id = position.position_id
    core.runtime.remaining_quantity = position.quantity
    core.runtime.average_entry_price = position.entry_price
    core.runtime.last_price = position.current_price
    core.runtime.highest_price_seen = position.highest_price
    core.runtime.highest_profit_percent = position.max_profit_percent
    core.runtime.partial_exit_done = position.partial_closed
    core.runtime.realized_profit = position.realized_pnl
    core.runtime.unrealized_profit = max(0.0, position.gross_pnl - position.realized_pnl)
    core.realized_profit = position.realized_pnl
    core.unrealized_profit = core.runtime.unrealized_profit
    core.fees_paid = position.total_fees
    core.recovery_mode = position.recovery_active
    core.recovery_state = RecoveryState.ACTIVE if position.recovery_active else RecoveryState.DISABLED
    core.status = _TM_TO_CORE_STATUS[position.status]
    core.is_open = position.status not in {
        PositionStatus.CLOSED,
        PositionStatus.CANCELLED,
        PositionStatus.FAILED,
    }
    core.last_update = now
    if not core.is_open:
        core.exit_reason = position.close_reason.name
    return core


def _close_reason(value: str) -> PositionCloseReason:
    if not value:
        return PositionCloseReason.NONE
    normalized = value.upper().replace(" ", "_")
    aliases = {
        "TAKE_PROFIT": PositionCloseReason.TAKE_PROFIT,
        "STOP_LOSS": PositionCloseReason.STOP_LOSS,
        "TRAILING_STOP": PositionCloseReason.TRAILING_STOP,
        "BREAK_EVEN": PositionCloseReason.BREAK_EVEN,
        "MANUAL": PositionCloseReason.MANUAL,
        "REVIEW_EXIT": PositionCloseReason.REVIEW_EXIT,
        "EMERGENCY_EXIT": PositionCloseReason.EMERGENCY_EXIT,
        "RECOVERY_FAILED": PositionCloseReason.RECOVERY_FAILED,
    }
    return aliases.get(normalized, PositionCloseReason.NONE)
