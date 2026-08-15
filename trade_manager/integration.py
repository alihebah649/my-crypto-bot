"""Runtime integration seam for Parts 6, 7 and 8.

This class intentionally does not own strategy decisions. It makes the ordering
of the contracts explicit and prevents a rejected entry from reaching execution
or a failed exit from mutating lifecycle state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .execution import ExecutionOrder, ExecutionPipeline, ExecutionResult, OrderSide
from .facade import PositionManagementFacade
from .integration_contract import EntryIntent, EntryResult
from .models import Position


@dataclass(slots=True)
class IntegrationConfig:
    require_full_fill_on_entry: bool = True
    require_full_fill_on_exit: bool = True


class TradeManagerIntegration:
    """Small coordinator used by a runtime to connect Part 6 -> 7 -> 8."""

    def __init__(self, facade: PositionManagementFacade,
                 execution: ExecutionPipeline,
                 config: Optional[IntegrationConfig] = None) -> None:
        self.facade = facade
        self.execution = execution
        self.config = config or IntegrationConfig()
        self.facade.controller.execution_pipeline = execution

    def open(self, intent: EntryIntent) -> EntryResult:
        risk = self.facade.validate_entry(
            equity=intent.equity,
            free_balance=intent.free_balance,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            current_exposure=intent.current_exposure,
            symbol_exposure=intent.symbol_exposure,
            spread_percent=intent.spread_percent,
            slippage_percent=intent.slippage_percent,
            estimated_fee=intent.estimated_fee,
        )
        if not risk.approved:
            return EntryResult(False, risk, message=f"ENTRY_RISK_REJECTED:{risk.reason}")

        order = ExecutionOrder(
            symbol=intent.symbol,
            side=OrderSide.BUY,
            quantity=intent.quantity,
            price=intent.entry_price,
        )
        execution = self.execution.execute(order)
        if not execution.success:
            return EntryResult(False, risk, execution=execution,
                                message=f"ENTRY_EXECUTION_FAILED:{execution.message}")
        if self.config.require_full_fill_on_entry and not execution.fully_filled:
            return EntryResult(False, risk, execution=execution,
                                message="ENTRY_REQUIRES_FULL_FILL")

        filled_qty = execution.executed_quantity or intent.quantity
        filled_price = execution.average_price or intent.entry_price
        position = self.facade.open_position(
            intent.symbol,
            filled_qty,
            filled_price,
            intent.stop_loss,
            entry_metadata={**intent.metadata, "execution_order_id": execution.exchange_order_id},
            risk_evaluation=risk,
        )
        return EntryResult(True, risk, execution=execution, position=position, message="APPROVED")

    def exit(self, position_id: str, exit_price: float, reason) -> Optional[Position]:
        return self.facade.close_position(position_id, exit_price, reason)
