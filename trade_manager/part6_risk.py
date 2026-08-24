"""Trade Manager Part 6 - normalized risk layer.

Spot-only risk boundary. Position sizing is capped by both account-risk sizing
and the configured target notional for the bot's normal entry size.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
import math
import threading
import time
from typing import Any, Optional

class RiskDecision(Enum):
    APPROVED=auto(); REJECTED=auto()
class RiskRejectReason(Enum):
    NONE=auto(); DAILY_LOSS_LIMIT=auto(); WEEKLY_LOSS_LIMIT=auto(); MONTHLY_LOSS_LIMIT=auto()
    MAX_OPEN_POSITIONS=auto(); MAX_OPEN_SCALP_POSITIONS=auto(); MAX_OPEN_SWING_POSITIONS=auto()
    MAX_SYMBOL_EXPOSURE=auto(); MAX_PORTFOLIO_EXPOSURE=auto(); CORRELATION_LIMIT=auto()
    ACCOUNT_BALANCE_TOO_LOW=auto(); INVALID_STOP_DISTANCE=auto(); INVALID_POSITION_SIZE=auto(); INVALID_RISK_PERCENT=auto()
    INVALID_MARKET_DATA=auto(); SPREAD_TOO_HIGH=auto(); SLIPPAGE_TOO_HIGH=auto(); MARKET_CLOSED=auto(); SYMBOL_DISABLED=auto()
    MIN_NOTIONAL_FAILED=auto(); LOT_SIZE_FAILED=auto(); PRICE_FILTER_FAILED=auto(); RISK_LOCKED=auto(); UNKNOWN_ERROR=auto()

@dataclass(slots=True)
class RiskLimits:
    max_daily_loss_percent: float=5.0; max_weekly_loss_percent: float=10.0; max_monthly_loss_percent: float=20.0
    # Aggregate hard ceiling. The effective lane limits below are enforced
    # independently: SCALP=15 and SWING=10.
    max_open_positions: int=25; max_symbol_exposure_percent: float=20.0; max_portfolio_exposure_percent: float=80.0
    max_risk_per_trade_percent: float=1.0
@dataclass(slots=True)
class PositionSizeResult:
    quantity: float; position_value: float; risk_amount: float; stop_distance: float; leverage_used: float; capital_used: float
@dataclass(slots=True)
class ExposureSnapshot:
    total_exposure_percent: float; symbol_exposure_percent: float; total_open_positions: int; account_equity: float
@dataclass(slots=True)
class RiskEvaluation:
    decision: RiskDecision; reject_reason: RiskRejectReason=RiskRejectReason.NONE; approved_risk_percent: float=0.0
    approved_position_size: Optional[PositionSizeResult]=None; metadata: dict[str,Any]=field(default_factory=dict)
@dataclass(slots=True)
class PositionSizingConfig:
    risk_per_trade_percent: float=1.0
    target_position_value: float=50.0
    minimum_position_size: float=10.0
    maximum_position_size: float=100000.0
    allow_fractional_quantity: bool=True; round_quantity_to_step: bool=True
@dataclass(slots=True)
class DailyRiskConfig:
    max_daily_loss_percent: float=5.0; max_weekly_loss_percent: float=10.0; max_monthly_loss_percent: float=20.0
    stop_trading_after_limit: bool=True
    # A realized loss below the configured daily/weekly/monthly limits must
    # not freeze the engine. The actual percentage thresholds below are the
    # authoritative circuit breakers.
    lock_after_realized_loss: bool=False
@dataclass(slots=True)
class ExposureConfig:
    max_open_positions: int=25
    max_scalp_positions: int=15
    max_swing_positions: int=10
    max_symbol_exposure_percent: float=20.0
    max_portfolio_exposure_percent: float=80.0
    # Keep same-mode duplicate protection. A symbol may have at most one
    # SCALP and one SWING position concurrently when this option is enabled.
    allow_multiple_positions_same_symbol: bool=False
    allow_dual_mode_same_symbol: bool=True
@dataclass(slots=True)
class CorrelationConfig:
    enabled: bool=True; maximum_correlation: float=0.80; lookback_candles: int=200
@dataclass(slots=True)
class MarketRiskConfig:
    maximum_spread_percent: float=0.30; maximum_slippage_percent: float=0.20; minimum_volume_usdt: float=500000.0
    reject_if_market_volatile: bool=False
@dataclass(slots=True)
class RiskSystemOptions:
    enable_position_sizing: bool=True; enable_daily_loss_control: bool=True; enable_exposure_control: bool=True
    enable_correlation_control: bool=True; enable_market_filters: bool=True
@dataclass(slots=True)
class RiskConfig:
    position_sizing: PositionSizingConfig=field(default_factory=PositionSizingConfig)
    daily_risk: DailyRiskConfig=field(default_factory=DailyRiskConfig)
    exposure: ExposureConfig=field(default_factory=ExposureConfig)
    correlation: CorrelationConfig=field(default_factory=CorrelationConfig)
    market: MarketRiskConfig=field(default_factory=MarketRiskConfig)
    options: RiskSystemOptions=field(default_factory=RiskSystemOptions)
@dataclass(slots=True)
class RiskRequest:
    symbol: str; side: str; entry_price: float; stop_loss: float; take_profit: Optional[float]; atr: float
    spread_percent: float; expected_slippage_percent: float; available_balance: float; account_equity: float
    signal_strength: float=0.0; metadata: dict[str,Any]=field(default_factory=dict)
@dataclass(slots=True)
class PortfolioSnapshot:
    account_balance: float; account_equity: float; used_margin: float; free_margin: float; floating_pnl: float
    daily_pnl: float; weekly_pnl: float; monthly_pnl: float; open_positions: int
    scalp_open_positions: int=0; swing_open_positions: int=0
@dataclass(slots=True)
class SymbolExposure:
    symbol: str; exposure_percent: float; open_positions: int; total_quantity: float; total_value: float
    open_trade_modes: tuple[str, ...]=()
@dataclass(slots=True)
class MarketContext:
    symbol: str; last_price: float; bid: float; ask: float; spread_percent: float; atr: float; volume: float
    volatility: float; timestamp: float
@dataclass(slots=True)
class RiskContext:
    request: RiskRequest; portfolio: PortfolioSnapshot; market: MarketContext; symbol_exposure: SymbolExposure
    correlation_score: float=0.0; metadata: dict[str,Any]=field(default_factory=dict)

class PositionSizeCalculator:
    def __init__(self, config: RiskConfig): self.config=config
    def calculate(self, *, account_equity: float, entry_price: float, stop_loss: float, leverage: float=1.0,
                  target_position_value: Optional[float]=None)->PositionSizeResult:
        if account_equity<=0 or entry_price<=0 or stop_loss<=0: raise ValueError("invalid sizing inputs")
        if leverage!=1.0: raise ValueError("spot-only Trade Manager requires leverage=1.0")
        distance=abs(entry_price-stop_loss)
        if distance<=0: raise ValueError("stop distance equals zero")
        risk_pct=self.config.position_sizing.risk_per_trade_percent/100.0
        if not 0<risk_pct<=1: raise ValueError("invalid risk percent")
        risk_amount=account_equity*risk_pct
        risk_quantity=risk_amount/distance
        risk_value=risk_quantity*entry_price
        configured_target=(self.config.position_sizing.target_position_value
                           if target_position_value is None else float(target_position_value))
        if configured_target<=0: raise ValueError("invalid target position value")
        value=min(configured_target,risk_value)
        quantity=value/entry_price
        actual_risk=quantity*distance
        return PositionSizeResult(quantity,value,actual_risk,distance,1.0,value)

class PositionSizeNormalizer:
    def __init__(self, exchange_info_provider: Any): self.exchange_info=exchange_info_provider
    def normalize(self, *, symbol: str, quantity: float, price: float)->float:
        if quantity<=0 or price<=0: raise ValueError("quantity and price must be positive")
        f=self.exchange_info.get_symbol_filters(symbol)
        if f is None: raise ValueError(f"No exchange filters found for {symbol}")
        step=float(f.step_size); minimum=float(f.min_qty); maximum=float(f.max_qty); min_value=float(f.min_notional)
        if step<=0: raise ValueError("invalid lot step")
        q=round(math.floor(quantity/step)*step,int(getattr(f,"quantity_precision",12)))
        if q<minimum: raise ValueError("LOT_SIZE_FAILED")
        q=min(q,maximum)
        if q*price<min_value: raise ValueError("MIN_NOTIONAL_FAILED")
        return q

class PositionFundingValidator:
    def __init__(self, risk_config: RiskConfig): self.config=risk_config
    def validate(self, *, account_equity: float, free_balance: float, position_value: float, capital_required: float, leverage: float=1.0)->tuple[bool,str]:
        if account_equity<=0:return False,"INVALID_ACCOUNT_EQUITY"
        if free_balance<=0:return False,"NO_FREE_BALANCE"
        if leverage!=1.0:return False,"LEVERAGE_NOT_ALLOWED_SPOT"
        if capital_required<=0:return False,"INVALID_CAPITAL_REQUIRED"
        if capital_required>free_balance:return False,"INSUFFICIENT_BALANCE"
        if position_value>self.config.position_sizing.maximum_position_size:return False,"MAX_POSITION_EXCEEDED"
        if position_value<self.config.position_sizing.minimum_position_size:return False,"POSITION_TOO_SMALL"
        return True,"APPROVED"
class AdvancedCapitalValidator:
    def __init__(self, risk_config: RiskConfig): self.config=risk_config
    def validate(self, *, free_balance: float, capital_required: float, account_equity: float)->tuple[bool,str]:
        if free_balance<=0 or account_equity<=0:return False,"INVALID_ACCOUNT"
        if capital_required>free_balance:return False,"INSUFFICIENT_BALANCE"
        if capital_required>account_equity:return False,"CAPITAL_EXCEEDS_EQUITY"
        return True,"APPROVED"

@dataclass(slots=True)
class LossSnapshot:
    daily_pnl: float=0.0; weekly_pnl: float=0.0; monthly_pnl: float=0.0
class LossTracker:
    def __init__(self):self._snapshot=LossSnapshot();self._lock=threading.RLock()
    def update(self, *, daily_pnl: float=0.0, weekly_pnl: float=0.0, monthly_pnl: float=0.0)->None:
        with self._lock:self._snapshot=LossSnapshot(daily_pnl,weekly_pnl,monthly_pnl)
    def snapshot(self)->LossSnapshot:
        with self._lock:return LossSnapshot(self._snapshot.daily_pnl,self._snapshot.weekly_pnl,self._snapshot.monthly_pnl)

class RiskLockManager:
    def __init__(self):self._state={"locked":False,"reason":"","locked_at":0.0,"unlock_at":None};self._lock=threading.RLock()
    def lock(self, *, reason: str, unlock_at: Optional[float]=None)->None:
        with self._lock:self._state={"locked":True,"reason":reason,"locked_at":time.time(),"unlock_at":unlock_at}
    def unlock(self)->None:
        with self._lock:self._state={"locked":False,"reason":"","locked_at":0.0,"unlock_at":None}
    def is_locked(self)->bool:
        with self._lock:
            if self._state["locked"] and self._state["unlock_at"] is not None and time.time()>=self._state["unlock_at"]:self.unlock()
            return bool(self._state["locked"])
    @property
    def reason(self)->str:
        with self._lock:return str(self._state["reason"])
    def snapshot(self)->dict[str,Any]:
        with self._lock:return dict(self._state)

class RiskController:
    def __init__(self, config: Optional[RiskConfig]=None, loss_tracker: Optional[LossTracker]=None, lock_manager: Optional[RiskLockManager]=None):
        self.config=config or RiskConfig();self.loss_tracker=loss_tracker or LossTracker();self.lock_manager=lock_manager or RiskLockManager()
    def evaluate(self, *, account: PortfolioSnapshot, symbol: str, signal: Any, market: MarketContext, symbol_exposure: Optional[SymbolExposure]=None, correlation_score: float=0.0)->RiskEvaluation:
        c=self.config; loss=self.loss_tracker.snapshot(); limits=c.daily_risk
        if c.options.enable_daily_loss_control and limits.lock_after_realized_loss and loss.daily_pnl < 0:
            if limits.stop_trading_after_limit:self.lock_manager.lock(reason=RiskRejectReason.DAILY_LOSS_LIMIT.name)
            return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.DAILY_LOSS_LIMIT,
                                  metadata={"daily_pnl": loss.daily_pnl, "lock_reason": RiskRejectReason.DAILY_LOSS_LIMIT.name,
                                            "gate": "REALIZED_LOSS_REENTRY_LOCK"})
        if self.lock_manager.is_locked():
            return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.RISK_LOCKED,metadata={"lock_reason":self.lock_manager.reason})
        if not symbol or market.last_price<=0 or account.account_equity<=0:return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.INVALID_MARKET_DATA)

        mode = str(signal or "SWING").upper()
        if mode == "SCALP":
            if account.scalp_open_positions >= c.exposure.max_scalp_positions:
                return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_OPEN_SCALP_POSITIONS,
                                       metadata={"trade_mode":"SCALP","open_positions":account.scalp_open_positions,
                                                 "max_open_positions":c.exposure.max_scalp_positions})
        elif mode == "SWING":
            if account.swing_open_positions >= c.exposure.max_swing_positions:
                return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_OPEN_SWING_POSITIONS,
                                       metadata={"trade_mode":"SWING","open_positions":account.swing_open_positions,
                                                 "max_open_positions":c.exposure.max_swing_positions})
        elif account.open_positions >= c.exposure.max_open_positions:
            return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_OPEN_POSITIONS,
                                   metadata={"trade_mode":mode,"open_positions":account.open_positions,
                                             "max_open_positions":c.exposure.max_open_positions})

        if account.open_positions>=c.exposure.max_open_positions:
            return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_OPEN_POSITIONS)
        if symbol_exposure:
            existing_modes={str(item).upper() for item in symbol_exposure.open_trade_modes if str(item).strip()}
            if symbol_exposure.exposure_percent>=c.exposure.max_symbol_exposure_percent:
                return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_SYMBOL_EXPOSURE,
                                       metadata={"trade_mode":mode,"existing_trade_modes":sorted(existing_modes),
                                                 "open_positions":symbol_exposure.open_positions})
            if not c.exposure.allow_multiple_positions_same_symbol:
                if c.exposure.allow_dual_mode_same_symbol and mode in {"SCALP","SWING"}:
                    # Exactly one position per lane is allowed for a symbol.
                    # A second position is valid only when it is the opposite lane.
                    if symbol_exposure.open_positions >= 2 or mode in existing_modes:
                        return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_SYMBOL_EXPOSURE,
                                               metadata={"trade_mode":mode,"existing_trade_modes":sorted(existing_modes),
                                                         "open_positions":symbol_exposure.open_positions,
                                                         "rule":"ONE_SCALP_PLUS_ONE_SWING_PER_SYMBOL"})
                elif symbol_exposure.open_positions>0:
                    return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_SYMBOL_EXPOSURE,
                                           metadata={"trade_mode":mode,"existing_trade_modes":sorted(existing_modes),
                                                     "open_positions":symbol_exposure.open_positions})
        if c.options.enable_exposure_control and account.used_margin/account.account_equity*100>=c.exposure.max_portfolio_exposure_percent:return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.MAX_PORTFOLIO_EXPOSURE)
        if c.options.enable_correlation_control and c.correlation.enabled and abs(correlation_score)>c.correlation.maximum_correlation:return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.CORRELATION_LIMIT)
        if c.options.enable_market_filters:
            if market.spread_percent>c.market.maximum_spread_percent:return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.SPREAD_TOO_HIGH)
            if market.volume<c.market.minimum_volume_usdt:return RiskEvaluation(RiskDecision.REJECTED,RiskRejectReason.INVALID_MARKET_DATA)
        checks=((loss.daily_pnl,limits.max_daily_loss_percent,RiskRejectReason.DAILY_LOSS_LIMIT),(loss.weekly_pnl,limits.max_weekly_loss_percent,RiskRejectReason.WEEKLY_LOSS_LIMIT),(loss.monthly_pnl,limits.max_monthly_loss_percent,RiskRejectReason.MONTHLY_LOSS_LIMIT))
        if c.options.enable_daily_loss_control:
            for pnl,limit,reason in checks:
                if pnl<0 and abs(pnl)>=account.account_equity*limit/100:
                    if limits.stop_trading_after_limit:self.lock_manager.lock(reason=reason.name)
                    return RiskEvaluation(RiskDecision.REJECTED,reason)
        return RiskEvaluation(RiskDecision.APPROVED,approved_risk_percent=c.position_sizing.risk_per_trade_percent)

@dataclass(slots=True)
class FinalRiskDecision:
    approved: bool; reason: str; risk_percent: float; position_size: float; stop_distance: float
class FinalRiskValidator:
    def __init__(self,risk_controller:RiskController,position_sizer:PositionSizeCalculator,stoploss_calculator:Any):self.risk_controller=risk_controller;self.position_sizer=position_sizer;self.stoploss_calculator=stoploss_calculator
    def validate(self, *, symbol:str, account:PortfolioSnapshot, entry_price:float, signal:Any, market:MarketContext, symbol_exposure:Optional[SymbolExposure]=None, correlation_score:float=0.0)->FinalRiskDecision:
        gate=self.risk_controller.evaluate(account=account,symbol=symbol,signal=signal,market=market,symbol_exposure=symbol_exposure,correlation_score=correlation_score)
        if gate.decision is not RiskDecision.APPROVED:return FinalRiskDecision(False,gate.reject_reason.name,0.0,0.0,0.0)
        distance=float(self.stoploss_calculator.calculate(signal=signal,market=market))
        if distance<=0:return FinalRiskDecision(False,RiskRejectReason.INVALID_STOP_DISTANCE.name,0.0,0.0,0.0)
        size=self.position_sizer.calculate(account_equity=account.account_equity,entry_price=entry_price,stop_loss=entry_price-distance,leverage=1.0)
        return FinalRiskDecision(True,"APPROVED",self.position_sizer.config.position_sizing.risk_per_trade_percent,size.quantity,distance)

__all__=["RiskDecision","RiskRejectReason","RiskLimits","PositionSizeResult","ExposureSnapshot","PositionSizingConfig","DailyRiskConfig","ExposureConfig","CorrelationConfig","MarketRiskConfig","RiskSystemOptions","RiskConfig","RiskRequest","PortfolioSnapshot","SymbolExposure","MarketContext","RiskContext","PositionSizeCalculator","PositionSizeNormalizer","PositionFundingValidator","AdvancedCapitalValidator","LossSnapshot","LossTracker","RiskLockManager","RiskController","FinalRiskDecision","FinalRiskValidator"]
