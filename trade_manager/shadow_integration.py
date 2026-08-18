"""Application composition for Shadow Trading Bot -> Trade Manager.

This module owns wiring only. It does not implement strategy, risk formulas,
or exchange execution. Strategy data is supplied by ``update_market`` and
execution is delegated to the existing core execution adapter through
``CoreExecutionGateway``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
import time
from typing import Any, Dict, Optional

from core.execution_adapter import ExecutionAdapter
from core.paper_execution_adapter import PaperExecutionAdapter

from .calculator import PositionCalculator
from .controller import PositionController
from .core_execution_gateway import CoreExecutionGateway
from .core_risk_gateway import CoreRiskGateway
from .facade import PositionManagementFacade
from .integration_contracts import RiskSizingRequest
from .models import Position, PositionStatus
from .part6_risk import LossTracker, MarketContext, PortfolioSnapshot, PositionSizeCalculator, RiskConfig, RiskController, SymbolExposure
from .repository import PositionRepository
from .risk_manager import PositionRiskManager


@dataclass(slots=True)
class ShadowMarketState:
    price: Dict[str, float] = field(default_factory=dict)
    bid: Dict[str, float] = field(default_factory=dict)
    ask: Dict[str, float] = field(default_factory=dict)
    spread_percent: Dict[str, float] = field(default_factory=dict)
    atr: Dict[str, float] = field(default_factory=dict)
    volume_usdt: Dict[str, float] = field(default_factory=dict)
    volatility: Dict[str, float] = field(default_factory=dict)
    ema100: Dict[str, float] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def update(self, symbol: str, *, price: float, bid: Optional[float] = None, ask: Optional[float] = None,
               spread_percent: float = 0.0, atr: float = 0.0, volume_usdt: float = 0.0,
               volatility: float = 0.0, ema100: float = 0.0) -> None:
        symbol = symbol.upper()
        if price <= 0:
            raise ValueError("market price must be positive")
        with self._lock:
            self.price[symbol] = float(price)
            self.bid[symbol] = float(bid if bid is not None else price)
            self.ask[symbol] = float(ask if ask is not None else price)
            self.spread_percent[symbol] = float(spread_percent)
            self.atr[symbol] = float(atr)
            self.volume_usdt[symbol] = float(volume_usdt)
            self.volatility[symbol] = float(volatility)
            self.ema100[symbol] = float(ema100)

    def get(self, symbol: str) -> MarketContext:
        symbol = symbol.upper()
        with self._lock:
            price = self.price.get(symbol, 0.0)
            return MarketContext(symbol=symbol, last_price=price, bid=self.bid.get(symbol, price),
                                 ask=self.ask.get(symbol, price), spread_percent=self.spread_percent.get(symbol, 0.0),
                                 atr=self.atr.get(symbol, 0.0), volume=self.volume_usdt.get(symbol, 0.0),
                                 volatility=self.volatility.get(symbol, 0.0), timestamp=time.time())


class _PortfolioProvider:
    def __init__(self, adapter: ExecutionAdapter, repository: PositionRepository, market: ShadowMarketState):
        self.adapter = adapter; self.repository = repository; self.market = market

    def snapshot(self) -> PortfolioSnapshot:
        balance = getattr(self.adapter, "balance", None)
        cash = float(getattr(balance, "cash", 0.0)); assets = dict(getattr(balance, "assets", {}))
        asset_value = sum(quantity * self.market.price.get(symbol, 0.0) for symbol, quantity in assets.items())
        equity = cash + asset_value
        cost_basis = sum(p.entry_price * p.quantity for p in self.repository.get_open_positions())
        return PortfolioSnapshot(account_balance=equity, account_equity=equity, used_margin=asset_value,
                                 free_margin=cash, floating_pnl=asset_value - cost_basis, daily_pnl=0.0,
                                 weekly_pnl=0.0, monthly_pnl=0.0,
                                 open_positions=len(self.repository.get_open_positions()))


class _MarketProvider:
    def __init__(self, state: ShadowMarketState): self.state = state
    def get_context(self, symbol: str) -> MarketContext: return self.state.get(symbol)


class _ExposureProvider:
    def __init__(self, repository: PositionRepository, market: ShadowMarketState):
        self.repository = repository; self.market = market

    def get_exposure(self, symbol: str) -> SymbolExposure:
        symbol = symbol.upper()
        active = {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED, PositionStatus.PARTIALLY_CLOSED}
        positions = [p for p in self.repository.get_by_symbol(symbol) if p.status in active]
        total_value = sum(p.quantity * self.market.price.get(symbol, p.current_price) for p in positions)
        return SymbolExposure(symbol=symbol, exposure_percent=0.0, open_positions=len(positions),
                              total_quantity=sum(p.quantity for p in positions), total_value=total_value)


class _PaperLossPeriodLedger:
    """Rebuild Part-6 period loss totals from persisted closed positions."""
    def __init__(self, tracker: LossTracker) -> None: self.tracker = tracker; self._lock = threading.RLock()

    def sync(self, positions: list[Position]) -> None:
        now = datetime.now(timezone.utc); day_key = now.strftime("%Y-%m-%d"); week_key = now.strftime("%G-W%V"); month_key = now.strftime("%Y-%m")
        daily = weekly = monthly = 0.0
        with self._lock:
            for position in positions:
                if position.status is not PositionStatus.CLOSED: continue
                closed = datetime.fromtimestamp(position.closed_at or position.opened_at, timezone.utc)
                if closed.strftime("%Y-%m-%d") == day_key: daily += float(position.realized_pnl)
                if closed.strftime("%G-W%V") == week_key: weekly += float(position.realized_pnl)
                if closed.strftime("%Y-%m") == month_key: monthly += float(position.realized_pnl)
            self.tracker.update(daily_pnl=daily, weekly_pnl=weekly, monthly_pnl=monthly)


class ShadowTradeManagerRuntime:
    """Fully composed Trade Manager runtime used by ``shadow_main.py``."""
    def __init__(self, *, initial_cash: float = 1000.0, fee_rate: float = 0.001,
                 execution_adapter: Optional[ExecutionAdapter] = None, risk_config: Optional[RiskConfig] = None,
                 persistence_dir: Optional[str] = None) -> None:
        self.market = ShadowMarketState(); self.persistence_dir = persistence_dir
        self.last_entry_diagnostics: Dict[str, dict] = {}
        position_state = paper_state = None
        if persistence_dir:
            os.makedirs(persistence_dir, exist_ok=True)
            position_state = os.path.join(persistence_dir, "positions.json"); paper_state = os.path.join(persistence_dir, "paper_account.json")
        self.repository = PositionRepository(persistence_path=position_state)
        self.execution_adapter = execution_adapter or PaperExecutionAdapter(initial_cash=initial_cash, fee_rate=fee_rate, state_path=paper_state)
        self.loss_tracker = LossTracker(); self.loss_ledger = _PaperLossPeriodLedger(self.loss_tracker)
        self.risk_config = risk_config or RiskConfig(); self.risk_controller = RiskController(self.risk_config, self.loss_tracker)
        self.position_sizer = PositionSizeCalculator(self.risk_config)
        self.portfolio_provider = _PortfolioProvider(self.execution_adapter, self.repository, self.market)
        self.risk_gateway = CoreRiskGateway(controller=self.risk_controller, position_sizer=self.position_sizer,
                                            portfolio_provider=self.portfolio_provider, market_provider=_MarketProvider(self.market),
                                            exposure_provider=_ExposureProvider(self.repository, self.market), quantity_normalizer=None)
        self.execution_gateway = CoreExecutionGateway(self.execution_adapter); self.calculator = PositionCalculator()
        self.position_risk = PositionRiskManager(market_context_provider=self._position_market_context,
                                                 atr_provider=self._atr_percent, ema_provider=self._ema_trend,
                                                 trailing_atr_multiplier=1.5, break_even_trigger_percent=1.5, max_holding_days=7.0)
        self.controller = PositionController(self.position_risk, self.repository, self.execution_gateway)
        self.facade = PositionManagementFacade(repository=self.repository, controller=self.controller, calculator=self.calculator,
                                               risk_manager=self.position_risk, execution_gateway=self.execution_gateway,
                                               risk_gateway=self.risk_gateway)
        if hasattr(self.execution_adapter, "connect"): self.execution_adapter.connect()
        self.loss_ledger.sync(self.repository.get_closed_positions())

    def update_market(self, symbol: str, **kwargs: Any) -> None:
        self.market.update(symbol, **kwargs)
        if hasattr(self.execution_adapter, "set_market_price"): self.execution_adapter.set_market_price(symbol, kwargs["price"])
        self.controller.update_market_price(symbol, kwargs["price"]); self.loss_ledger.sync(self.repository.get_closed_positions())

    def open_position(self, symbol: str, entry_price: float, stop_loss: float) -> Optional[Position]:
        trace = {"symbol": symbol, "started_at": time.time(), "risk_gateway": "NOT_RUN", "risk_reason": None,
                 "risk_quantity": 0.0, "risk_position_value": 0.0, "risk_capital_required": 0.0, "risk_metadata": {},
                 "facade": "NOT_RUN", "execution": "NOT_RUN", "execution_outcome": None, "result": "UNKNOWN"}
        self.last_entry_diagnostics[symbol] = trace
        account = self.portfolio_provider.snapshot()
        trace.update({"account_equity": account.account_equity, "free_balance": account.free_margin,
                      "open_positions": account.open_positions, "entry_price": entry_price, "stop_loss": stop_loss})
        approval = self.risk_gateway.approve(RiskSizingRequest(symbol=symbol, entry_price=entry_price, stop_loss=stop_loss,
                                                              account_equity=account.account_equity, free_balance=account.free_margin, leverage=1.0))
        trace.update({"risk_gateway": "PASS" if approval.approved else "REJECT", "risk_reason": approval.reason,
                      "risk_quantity": approval.quantity, "risk_position_value": approval.position_value,
                      "risk_capital_required": approval.capital_required, "risk_metadata": dict(approval.metadata)})
        if not approval.approved:
            trace.update({"result": "REJECTED_AT_RISK_GATE", "finished_at": time.time()}); return None
        trace["facade"] = "CALLED"
        position = self.facade.open_position(symbol=symbol, quantity=approval.quantity, entry_price=entry_price,
                                              stop_loss=stop_loss, account_equity=account.account_equity,
                                              free_balance=account.free_margin)
        facade_trace = dict(self.facade.last_entry_diagnostic)
        trace["facade_diagnostic"] = facade_trace
        if position is not None:
            trace.update({"execution": "FILLED", "execution_outcome": {"quantity": position.quantity,
                         "entry_price": position.entry_price, "exchange_order_id": position.exchange_order_id},
                         "result": "POSITION_OPENED"})
        else:
            trace.update({"execution": facade_trace.get("execution_gateway", "REJECTED_OR_FAILED"),
                          "execution_outcome": facade_trace.get("execution_outcome"),
                          "result": facade_trace.get("result", "REJECTED_AFTER_INITIAL_RISK_PASS")})
        trace["finished_at"] = time.time(); return position

    def evaluate_position(self, symbol: str) -> None:
        for position in self.repository.get_by_symbol(symbol):
            if position.status not in {PositionStatus.OPEN, PositionStatus.HOLD}: continue
            decision = self.position_risk.evaluate(position); self.facade.execute_decision(position.position_id, decision)
        self.loss_ledger.sync(self.repository.get_closed_positions())

    def _position_market_context(self, symbol: str) -> Dict[str, Any]:
        state = self.market.get(symbol); ema = self.market.ema100.get(symbol, 0.0)
        trend = "BULLISH" if ema and state.last_price > ema else "NEUTRAL"
        return {"ema_100": trend, "market": {"overall": trend}, "volatility": "NORMAL"}

    def _atr_percent(self, symbol: str) -> Optional[float]:
        price = self.market.price.get(symbol, 0.0); atr = self.market.atr.get(symbol, 0.0)
        if price <= 0 or atr <= 0: return None
        return atr / price * 100.0

    def _ema_trend(self, symbol: str) -> str:
        ema = self.market.ema100.get(symbol, 0.0); price = self.market.price.get(symbol, 0.0)
        if not ema or not price: return "NEUTRAL"
        return "BULLISH" if price > ema else "NEUTRAL"


__all__ = ["ShadowMarketState", "ShadowTradeManagerRuntime"]
