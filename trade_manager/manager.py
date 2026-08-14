from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .execution import ExecutionOrder, ExecutionPipeline, ExecutionResult, OrderSide
from .models import (ExitReason, ManagedPosition, ProtectionAction, TradeContext,
                     TradeManagerConfig, TradeStatistics)
from .protection import ProtectionLogicEvaluator
from .risk import RiskConfig, RiskManager

logger = logging.getLogger("TradeManager")


@dataclass(slots=True)
class CloseResult:
    success: bool
    position: Optional[ManagedPosition]
    execution: Optional[ExecutionResult]
    net_pnl: float = 0.0
    message: str = ""


class TradeManager:
    """Unified Part 1-7 state layer with the Section-8 contract boundary."""

    VERSION = "1.0.0-integrated"

    def __init__(self, *, config: TradeManagerConfig | None = None,
                 risk_manager: RiskManager | None = None,
                 execution_pipeline: ExecutionPipeline | None = None,
                 repository=None, ledger=None):
        self.config = config or TradeManagerConfig()
        self.risk = risk_manager or RiskManager(RiskConfig(
            max_open_positions=self.config.max_open_positions,
            max_symbol_exposure_percent=self.config.max_symbol_exposure_percent,
            max_portfolio_exposure_percent=self.config.max_portfolio_exposure_percent,
            max_risk_per_trade_percent=self.config.risk_per_trade_percent,
        ))
        self.execution = execution_pipeline
        self.repository = repository
        self.ledger = ledger
        self.protection = ProtectionLogicEvaluator(self.config)
        self._positions: dict[str, ManagedPosition] = {}
        self._closed: list[ManagedPosition] = []
        self._lock = threading.RLock()
        self.statistics = TradeStatistics()
        self.price_cache: dict[str, float] = {}

    @property
    def positions(self):
        with self._lock:
            return dict(self._positions)

    def get_open_positions(self) -> list[ManagedPosition]:
        with self._lock:
            return [p for p in self._positions.values() if p.status == "OPEN"]

    def get_position(self, trade_id: str) -> Optional[ManagedPosition]:
        with self._lock:
            return self._positions.get(trade_id)

    def get_position_by_symbol(self, symbol: str) -> Optional[ManagedPosition]:
        with self._lock:
            for p in self._positions.values():
                if p.symbol == symbol and p.status == "OPEN":
                    return p
        return None

    def open_position(self, symbol: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: float | None = None,
                      atr: float = 0.0, metadata: dict | None = None) -> ManagedPosition:
        if not symbol or quantity <= 0 or entry_price <= 0:
            raise ValueError("Invalid position parameters")
        with self._lock:
            if self.get_position_by_symbol(symbol) is not None:
                raise ValueError(f"Position already open for {symbol}")
            position = ManagedPosition(symbol=symbol, quantity=quantity,
                                       entry_price=entry_price, stop_loss=stop_loss,
                                       take_profit=take_profit, atr_at_entry=atr,
                                       metadata=metadata or {})
            self._positions[position.trade_id] = position
            self.statistics.total_opened += 1
            self.statistics.total_volume += position.cost_value
            if self.repository and hasattr(self.repository, "add"):
                self.repository.add(position)
            return position

    def update_price(self, symbol: str, price: float, atr: float | None = None):
        position = self.get_position_by_symbol(symbol)
        if position is None:
            return None
        decision = self.protection.evaluate(position, price, atr)
        if decision.action == ProtectionAction.MOVE_TO_BREAK_EVEN and decision.new_stop_loss:
            position.stop_loss = max(position.stop_loss, decision.new_stop_loss)
            position.break_even_done = True
        elif decision.action == ProtectionAction.UPDATE_STOP and decision.new_stop_loss:
            position.stop_loss = max(position.stop_loss, decision.new_stop_loss)
        elif decision.action == ProtectionAction.CLOSE_POSITION:
            return self.close_position(position.trade_id, price, decision.close_reason or ExitReason.EXTERNAL)
        elif decision.action == ProtectionAction.REVIEW_REQUIRED:
            self.statistics.total_review_required += 1
        position.last_update = time.time() if hasattr(position, "last_update") else position.opened_at
        self.price_cache[symbol] = price
        return decision

    def close_position(self, trade_id: str, exit_price: float,
                       reason: ExitReason = ExitReason.MANUAL,
                       *, execute: bool = False) -> CloseResult:
        with self._lock:
            position = self._positions.get(trade_id)
            if position is None:
                return CloseResult(False, None, None, message="POSITION_NOT_FOUND")
            if exit_price <= 0:
                return CloseResult(False, position, None, message="INVALID_EXIT_PRICE")

            execution = None
            if execute:
                if self.execution is None:
                    return CloseResult(False, position, None, message="EXECUTION_PIPELINE_NOT_CONFIGURED")
                execution = self.execution.execute(ExecutionOrder(
                    symbol=position.symbol, side=OrderSide.SELL, quantity=position.quantity))
                if not execution.success:
                    return CloseResult(False, position, execution, message=execution.message)
                exit_price = execution.average_price or exit_price

            gross = (exit_price - position.entry_price) * position.quantity
            entry_fee = position.entry_price * position.quantity * self.config.fee_rate
            exit_fee = exit_price * position.quantity * self.config.fee_rate
            actual_fee = execution.commission if execution else 0.0
            fees = max(actual_fee, entry_fee + exit_fee)
            net = gross - fees
            position.current_price = exit_price
            position.realized_pnl = net
            position.fees_paid = fees
            position.close_reason = reason.value
            position.status = "CLOSED"
            self._closed.append(position)
            self._positions.pop(trade_id, None)
            self.statistics.total_closed += 1
            self.statistics.total_realized_pnl += net
            self.statistics.total_fees += fees
            if net >= 0:
                self.statistics.total_wins += 1
            else:
                self.statistics.total_losses += 1
            if self.repository and hasattr(self.repository, "save"):
                self.repository.save(position)
            if self.ledger and hasattr(self.ledger, "record_trade_exit"):
                self.ledger.record_trade_exit(position, net, reason.value)
            return CloseResult(True, position, execution, net, "CLOSED")

    def evaluate_risk(self, *, equity: float, free_balance: float, entry_price: float,
                      stop_loss: float, current_exposure: float = 0.0,
                      symbol_exposure: float = 0.0, spread_percent: float = 0.0,
                      slippage_percent: float = 0.0):
        return self.risk.evaluate(
            equity=equity, free_balance=free_balance, entry_price=entry_price,
            stop_loss=stop_loss, open_positions=len(self.get_open_positions()),
            current_exposure=current_exposure, symbol_exposure=symbol_exposure,
            spread_percent=spread_percent, slippage_percent=slippage_percent)

    def sync_portfolio_state(self, equity: float, free_balance: float) -> dict:
        with self._lock:
            exposure = sum(p.position_value for p in self._positions.values())
            unrealized = sum(p.unrealized_pnl for p in self._positions.values())
            self.statistics.total_unrealized_pnl = unrealized
            return {"equity": equity, "free_balance": free_balance,
                    "exposure": exposure, "unrealized_pnl": unrealized,
                    "open_positions": len(self._positions)}

    def get_statistics(self) -> TradeStatistics:
        with self._lock:
            return self.statistics
