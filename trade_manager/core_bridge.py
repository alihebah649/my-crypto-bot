"""Bridge between the canonical Trade Manager Part-8 position and core models.

Integration rule:
- ``core.models.Position`` remains the portfolio/accounting model.
- ``trade_manager.models.Position`` remains the lifecycle/risk model.
- This bridge is the only place where the two position representations are
  translated. Neither side should import the other's model directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models import Position as CorePosition
from core.models import RecoveryState as CoreRecoveryState
from core.models import TradeType

from .models import Position, PositionCloseReason, PositionSide, PositionStatus


_CORE_TO_TM_STATUS = {
    "OPEN": PositionStatus.OPEN,
    "RECOVERY": PositionStatus.HOLD,
    "PAUSED": PositionStatus.REVIEW_REQUIRED,
    "CLOSED": PositionStatus.CLOSED,
}


def from_core_position(source: CorePosition) -> Position:
    """Create a Trade Manager position snapshot from a core portfolio position."""
    status_name = getattr(source.status, "value", str(source.status))
    status = _CORE_TO_TM_STATUS.get(status_name, PositionStatus.OPEN)
    current_price = source.runtime.last_price or source.entry_price
    close_reason = PositionCloseReason.NONE
    if source.exit_reason:
        try:
            close_reason = PositionCloseReason[source.exit_reason]
        except KeyError:
            close_reason = PositionCloseReason.MANUAL

    metadata: dict[str, Any] = dict(source.runtime.metadata)
    metadata.update({
        "core_trade_id": source.trade_id,
        "strategy_name": source.strategy_name,
        "strategy_version": source.strategy_version,
        "run_id": source.run_id,
        "trade_type": getattr(source.trade_type, "value", str(source.trade_type)),
        "recovery_state": getattr(source.recovery_state, "value", str(source.recovery_state)),
    })

    opened_at = source.entry_time.timestamp() if isinstance(source.entry_time, datetime) else datetime.now(timezone.utc).timestamp()
    closed_at = None
    if not source.is_open:
        closed_at = source.last_update.timestamp() if isinstance(source.last_update, datetime) else None

    position = Position(
        position_id=source.trade_id or f"CORE-{source.symbol}",
        symbol=source.symbol,
        side=PositionSide.LONG,
        status=status,
        quantity=source.runtime.remaining_quantity or source.quantity,
        entry_price=source.entry_price,
        current_price=current_price,
        stop_loss=source.stop_loss,
        take_profit=source.take_profit or None,
        highest_price=source.highest_price or source.entry_price,
        lowest_price=source.entry_price,
        opened_at=opened_at,
        closed_at=closed_at,
        close_reason=close_reason,
        gross_pnl=source.realized_profit + source.fees_paid,
        realized_pnl=source.realized_profit,
        total_fees=source.fees_paid,
        metadata=metadata,
    )
    position.update_highest_price(current_price)
    position.update_lowest_price(current_price)
    position.update_max_profit(current_price)
    position.update_max_drawdown(current_price)
    position.hold_context["core_recovery_mode"] = source.recovery_mode
    return position


def apply_to_core_position(source: Position, target: CorePosition) -> CorePosition:
    """Apply lifecycle/risk state back to the existing core position object."""
    target.stop_loss = source.stop_loss
    target.take_profit = source.take_profit or 0.0
    target.highest_price = source.highest_price
    target.trailing_active = source.status == PositionStatus.OPEN and target.trailing_active
    target.break_even_active = source.metadata.get("break_even_activated", target.break_even_active)
    target.unrealized_profit = (source.current_price - source.entry_price) * source.quantity
    target.realized_profit = source.realized_pnl
    target.fees_paid = source.total_fees
    target.exit_reason = source.close_reason.name if source.close_reason != PositionCloseReason.NONE else target.exit_reason
    target.is_open = source.status != PositionStatus.CLOSED
    target.last_update = datetime.now(timezone.utc)

    if source.status == PositionStatus.HOLD:
        target.recovery_mode = True
        target.recovery_state = CoreRecoveryState.ACTIVE
    elif source.status == PositionStatus.REVIEW_REQUIRED:
        target.recovery_mode = True
        target.recovery_state = CoreRecoveryState.WAITING
    elif source.status == PositionStatus.CLOSED:
        target.recovery_mode = False
        target.recovery_state = CoreRecoveryState.FINISHED

    target.runtime.remaining_quantity = source.quantity
    target.runtime.last_price = source.current_price
    target.runtime.highest_price_seen = source.highest_price
    target.runtime.unrealized_profit = target.unrealized_profit
    target.runtime.realized_profit = source.realized_pnl
    target.runtime.break_even_price = source.stop_loss if source.metadata.get("break_even_activated") else target.runtime.break_even_price
    target.runtime.last_update = target.last_update
    target.runtime.metadata.update(source.metadata)
    return target


class CorePositionBridge:
    """Small stateless adapter used by the main runtime and synchronization layer."""

    @staticmethod
    def from_core(position: CorePosition) -> Position:
        return from_core_position(position)

    @staticmethod
    def apply_to_core(position: Position, core_position: CorePosition) -> CorePosition:
        return apply_to_core_position(position, core_position)
