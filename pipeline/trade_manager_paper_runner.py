"""Paper runner with Trade Manager as the execution/lifecycle boundary.

The existing market/indicator/recovery loop is retained for stability, but
order execution and canonical position lifecycle now pass through:
Part 6 Risk -> Part 7 Execution -> Part 8 Position.
The core PortfolioEngine remains the accounting projection for compatibility.
"""
from __future__ import annotations

import logging

from core.models import Position as CorePosition
from core.models import TradeType
from trade_manager import (
    PositionCalculator,
    PositionCloseReason,
    PositionController,
    PositionManagementFacade,
    PositionRepository,
    PositionRiskManager,
    RiskManager,
    ExecutionPipeline as TMExecutionPipeline,
    CoreExecutionBrokerAdapter,
    ExecutionOrder,
    OrderSide as TMOrderSide,
)

from .paper_trading_runner import PaperTradingRunner

logger = logging.getLogger("ShadowTrading.TradeManagerPaperRunner")


class TradeManagerPaperTradingRunner(PaperTradingRunner):
    """Same paper strategy loop, with Trade Manager owning order execution."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        repository = PositionRepository()
        controller = PositionController(PositionRiskManager(), repository)
        broker = CoreExecutionBrokerAdapter(
            self.paper_adapter,
            strategy_name="Shadow Trading System V3",
        )
        tm_execution = TMExecutionPipeline(broker)
        self.trade_manager = PositionManagementFacade(
            repository=repository,
            controller=controller,
            calculator=PositionCalculator(),
            risk_manager=PositionRiskManager(),
            entry_risk_manager=RiskManager(),
            execution_pipeline=tm_execution,
        )
        self.tm_execution = tm_execution
        logger.info("Trade Manager is now the canonical paper execution boundary")

    def _consider_entry(self, symbol, state) -> None:
        if state.score < self.BUY_SCORE if hasattr(self, "BUY_SCORE") else False:
            return
        if self.portfolio.has_position(symbol) or self.trade_manager.controller.has_position(symbol):
            return

        snapshot = self.portfolio.snapshot
        stop_loss = max(0.0, state.price - (state.atr * 2.0))
        risk = self.trade_manager.validate_entry(
            equity=snapshot.equity,
            free_balance=snapshot.free_balance,
            entry_price=state.price,
            stop_loss=stop_loss,
            current_exposure=getattr(snapshot, "market_value", snapshot.invested),
            symbol_exposure=0.0,
            estimated_fee=state.price * (1.0 - 0.0) * 0.001,
        )
        if not risk.approved:
            logger.info("TM ENTRY REJECTED %s: %s", symbol, risk.reason)
            return

        position_value = risk.position_size
        quantity = position_value / state.price if state.price > 0 else 0.0
        if quantity <= 0:
            return

        position, execution = self.trade_manager.open_position_with_execution(
            symbol=symbol,
            quantity=quantity,
            entry_price=state.price,
            stop_loss=stop_loss,
            entry_metadata={"paper": True, "score": state.score},
            risk_evaluation=risk,
        )
        if position is None:
            logger.warning("TM PAPER BUY failed %s: %s", symbol, execution.message)
            return

        core_position = CorePosition(
            symbol=symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit or 0.0,
            highest_price=position.entry_price,
            trade_type=TradeType.SCALPING_SWING,
            trade_id=execution.exchange_order_id or position.position_id,
            strategy_name="Shadow Trading System V3",
            strategy_version="paper-integrated",
            run_id=f"paper-{self._cycle}",
        )
        self.portfolio.open_position(core_position)
        logger.info("TM PAPER BUY %s qty=%.10f price=%.8f", symbol, position.quantity, position.entry_price)

    def _paper_sell(self, symbol: str, price: float, reason: str) -> None:
        core_position = self.portfolio.get_position(symbol)
        tm_positions = self.trade_manager.controller.get_symbol_positions(symbol)
        tm_position = next((p for p in tm_positions if p.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}), None)
        if core_position is None or tm_position is None:
            logger.warning("TM SELL skipped %s: lifecycle position missing", symbol)
            return

        reason_map = {
            "STOP_LOSS": PositionCloseReason.STOP_LOSS,
            "TRAILING_STOP": PositionCloseReason.TRAILING_STOP,
            "BREAK_EVEN": PositionCloseReason.BREAK_EVEN,
            "SIGNAL": PositionCloseReason.TAKE_PROFIT,
        }
        close_reason = reason_map.get(reason.split(":", 1)[0], PositionCloseReason.MANUAL)
        closed = self.trade_manager.close_position(tm_position.position_id, price, close_reason)
        if closed is None or closed.status.name != "CLOSED":
            logger.warning("TM PAPER SELL did not close %s", symbol)
            return

        result = self.paper_adapter.orders.get(closed.exit_metadata.get("execution_order_id"))
        fees = float(getattr(getattr(result, "fees", None), "total", 0.0) or 0.0)
        accounting_closed = self.portfolio.close_position(
            symbol,
            exit_price=closed.current_price,
            fees=fees,
            exit_reason=reason,
            strategy_version=core_position.strategy_version,
            run_id=core_position.run_id,
        )
        if accounting_closed is None:
            raise RuntimeError("Trade Manager/Core portfolio divergence after paper SELL")
        logger.info("TM PAPER SELL %s qty=%.10f price=%.8f reason=%s", symbol, closed.quantity, closed.current_price, reason)
