"""8.4 - Position risk, smart-hold/recovery and exit decisions."""
import logging
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional
from .calculator import PositionCalculator
from .models import Position, PositionStatus

logger = logging.getLogger(__name__)


class PositionExitReason(Enum):
    NONE = auto()
    STOP_LOSS = auto()
    TAKE_PROFIT = auto()
    TRAILING_STOP = auto()
    BREAK_EVEN = auto()
    REVIEW_REQUIRED = auto()
    RECOVERY_FAILED = auto()


@dataclass(slots=True)
class PositionExitDecision:
    should_exit: bool
    reason: PositionExitReason
    exit_price: float = 0.0
    message: str = ""
    hold_reason: str = ""
    review_required: bool = False
    recovery_score: float = 0.0


class PositionRiskManager:
    def __init__(self, market_context_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
                 atr_provider: Optional[Callable[[str], Any]] = None,
                 ema_provider: Optional[Callable[[str], Any]] = None,
                 btc_trend_provider: Optional[Callable[[], str]] = None,
                 trailing_atr_multiplier: float = 1.5,
                 break_even_trigger_percent: float = 1.5,
                 max_holding_days: float = 7.0,
                 min_recovery_score: float = 0.40,
                 min_net_profit_percent: float = 0.30,
                 reward_to_risk_ratio: float = 1.0,
                 trailing_take_profit_enabled: bool = True,
                 trailing_take_profit_activation_r: float = 2.0,
                 trailing_take_profit_lock_r: float = 1.0,
                 calculator: Optional[PositionCalculator] = None):
        if min_net_profit_percent < 0:
            raise ValueError("min_net_profit_percent must be non-negative")
        if reward_to_risk_ratio < 0:
            raise ValueError("reward_to_risk_ratio must be non-negative")
        if trailing_take_profit_activation_r < 0:
            raise ValueError("trailing_take_profit_activation_r must be non-negative")
        if trailing_take_profit_lock_r < 0:
            raise ValueError("trailing_take_profit_lock_r must be non-negative")
        if trailing_take_profit_enabled and trailing_take_profit_lock_r >= trailing_take_profit_activation_r:
            raise ValueError("trailing_take_profit_lock_r must be below activation_r")
        self.market_context_provider = market_context_provider
        self.atr_provider = atr_provider
        self.ema_provider = ema_provider
        self.btc_trend_provider = btc_trend_provider
        self.trailing_atr_multiplier = trailing_atr_multiplier
        self.break_even_trigger = break_even_trigger_percent
        self.max_holding_days = max_holding_days
        self.min_recovery_score = min_recovery_score
        self.min_net_profit_percent = min_net_profit_percent
        self.reward_to_risk_ratio = reward_to_risk_ratio
        self.trailing_take_profit_enabled = trailing_take_profit_enabled
        self.trailing_take_profit_activation_r = trailing_take_profit_activation_r
        self.trailing_take_profit_lock_r = trailing_take_profit_lock_r
        self.calculator = calculator or PositionCalculator()
        self._hold_decisions = []
        self._review_decisions = []

    def evaluate(self, position: Position) -> PositionExitDecision:
        self._update_position_metrics(position)
        position.hold_context = self._get_market_context(position.symbol)
        if "initial_stop_loss" not in position.metadata:
            position.metadata["initial_stop_loss"] = position.stop_loss

        if self.should_move_to_break_even(position):
            be = self.calculator.break_even_price(position)
            if position.stop_loss < be:
                position.stop_loss = be
                position.metadata["break_even_activated"] = True

        review = self._check_review_required(position)
        if review.review_required:
            return review

        stop = self._check_stop_loss(position)
        if stop.should_exit:
            return stop

        take_profit = self._check_take_profit(position)
        if take_profit.should_exit:
            return take_profit

        hold = self._check_hold_with_market_context(position)
        if hold.should_exit or hold.hold_reason:
            return hold

        if self._is_profitable(position):
            trailing = self._check_trailing_stop(position)
            if trailing.should_exit:
                return trailing

        return PositionExitDecision(False, PositionExitReason.NONE)

    def should_move_to_break_even(self, position: Position) -> bool:
        """Return True once the configured gross price gain reaches the BE trigger.

        The helper is intentionally side-effect free.  The caller is responsible
        for moving the stop to the fee-aware break-even price.  Keeping the trigger
        separate from the mutation preserves the existing exit-policy ordering.
        """
        if position.entry_price <= 0 or position.current_price <= 0:
            return False
        if position.metadata.get("break_even_activated"):
            return False
        gain_percent = ((position.current_price - position.entry_price) /
                        position.entry_price) * 100.0
        return gain_percent >= self.break_even_trigger

    def _update_position_metrics(self, position: Position) -> None:
        position.update_highest_price(position.current_price)
        position.update_lowest_price(position.current_price)
        position.update_max_profit(position.current_price)
        position.update_max_drawdown(position.current_price)

    def _get_market_context(self, symbol: str) -> Dict[str, Any]:
        context: Dict[str, Any] = {"ema_100": None, "atr": None, "btc_trend": None,
                                   "volatility": "normal", "recovery_potential": 0.0}
        try:
            if self.ema_provider:
                context["ema_100"] = self.ema_provider(symbol)
            if self.atr_provider:
                context["atr"] = self.atr_provider(symbol)
            if self.btc_trend_provider:
                context["btc_trend"] = self.btc_trend_provider()
            if self.market_context_provider:
                supplied = self.market_context_provider(symbol)
                if supplied:
                    context.update(supplied)
            context["recovery_potential"] = self._calculate_market_recovery_score(context)
        except Exception as exc:
            logger.warning("Failed to get market context: %s", exc)
        return context

    @staticmethod
    def _trend_value(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            return value.get("trend")
        return value if isinstance(value, str) else None

    def _calculate_market_recovery_score(self, context: Dict[str, Any]) -> float:
        score = 0.0
        if self._trend_value(context.get("ema_100")) == "BULLISH":
            score += 0.25
        elif self._trend_value(context.get("ema_100")) == "NEUTRAL":
            score += 0.125
        atr = context.get("atr")
        volatility = atr.get("volatility") if isinstance(atr, dict) else context.get("volatility")
        if volatility == "LOW":
            score += 0.15
        elif volatility == "NORMAL":
            score += 0.075
        btc = self._trend_value(context.get("btc_trend"))
        if btc == "BULLISH":
            score += 0.10
        elif btc == "NEUTRAL":
            score += 0.05
        market = context.get("market", {})
        overall = market.get("overall") if isinstance(market, dict) else None
        if overall == "BULLISH":
            score += 0.10
        elif overall == "NEUTRAL":
            score += 0.05
        return min(1.0, score)

    def _check_hold_with_market_context(self, position: Position) -> PositionExitDecision:
        pnl = self._get_pnl_percent(position)
        if pnl >= 0:
            if position.status == PositionStatus.HOLD:
                position.status = PositionStatus.OPEN
            return PositionExitDecision(False, PositionExitReason.NONE)
        recovery = float(position.hold_context.get("recovery_potential", 0.0))
        loss_factor = 1.0 - min(1.0, abs(pnl) / 10.0)
        adjusted = recovery * (0.7 + 0.3 * loss_factor)
        self._hold_decisions.append({"symbol": position.symbol, "pnl_percent": pnl,
                                     "recovery_score": recovery, "adjusted_score": adjusted,
                                     "timestamp": time.time()})
        if adjusted >= self.min_recovery_score:
            position.status = PositionStatus.HOLD
            if position.entered_hold_at is None:
                position.entered_hold_at = time.time()
            position.hold_reason = f"Recovery score: {adjusted:.2f} (market: {recovery:.2f})"
            position.metadata["hold_recovery_score"] = adjusted
            position.metadata["hold_market_score"] = recovery
            return PositionExitDecision(False, PositionExitReason.NONE,
                                        hold_reason=position.hold_reason,
                                        recovery_score=adjusted)
        if pnl < -5.0:
            return PositionExitDecision(True, PositionExitReason.RECOVERY_FAILED,
                                        position.current_price,
                                        f"Large loss ({pnl:.2f}%) with low recovery ({adjusted:.2f})",
                                        recovery_score=adjusted)
        if position.status == PositionStatus.HOLD:
            position.status = PositionStatus.OPEN
        return PositionExitDecision(False, PositionExitReason.NONE)

    def _check_stop_loss(self, position: Position) -> PositionExitDecision:
        if position.current_price <= position.stop_loss:
            reason = (PositionExitReason.BREAK_EVEN if position.metadata.get("break_even_activated")
                      else PositionExitReason.STOP_LOSS)
            return PositionExitDecision(True, reason, position.current_price,
                                        "Stop Loss / Break Even Triggered")
        return PositionExitDecision(False, PositionExitReason.NONE)

    def _check_take_profit(self, position: Position) -> PositionExitDecision:
        if position.take_profit is not None and position.current_price >= position.take_profit:
            if self.trailing_take_profit_enabled:
                position.metadata["take_profit_reached"] = True
                return PositionExitDecision(False, PositionExitReason.NONE,
                                            position.current_price,
                                            "Take Profit reached; trailing take-profit remains active")
            return PositionExitDecision(True, PositionExitReason.TAKE_PROFIT,
                                        position.current_price, "Take Profit Triggered")
        return PositionExitDecision(False, PositionExitReason.NONE)

    def _initial_stop_risk_percent(self, position: Position) -> float:
        initial_stop_loss = position.metadata.get("initial_stop_loss", position.stop_loss)
        if position.entry_price <= 0 or initial_stop_loss <= 0:
            return 0.0
        return abs(position.entry_price - initial_stop_loss) / position.entry_price * 100.0

    def _required_net_profit_percent(self, position: Position) -> float:
        stop_risk_percent = self._initial_stop_risk_percent(position)
        return max(self.min_net_profit_percent, stop_risk_percent * self.reward_to_risk_ratio)

    def _price_for_net_profit_percent(self, position: Position, target_net_profit_percent: float) -> float:
        return position.entry_price * (1.0 + self.calculator.entry_fee_rate + target_net_profit_percent / 100.0) / (1.0 - self.calculator.exit_fee_rate)

    def _minimum_profitable_exit_price(self, position: Position) -> float:
        required_net_profit_percent = self._required_net_profit_percent(position)
        return self._price_for_net_profit_percent(position, required_net_profit_percent)

    def _trailing_take_profit_floor_percent(self, position: Position, required_net_profit_percent: float) -> float:
        if not self.trailing_take_profit_enabled:
            return required_net_profit_percent
        risk_percent = self._initial_stop_risk_percent(position)
        if risk_percent <= 0:
            return required_net_profit_percent
        peak_net_profit_percent = self.calculator.calculate(position, position.highest_price).net_pnl_percent
        activation_percent = max(required_net_profit_percent, risk_percent * self.trailing_take_profit_activation_r)
        if peak_net_profit_percent < activation_percent:
            return required_net_profit_percent
        locked_percent = peak_net_profit_percent - (risk_percent * self.trailing_take_profit_lock_r)
        return max(required_net_profit_percent, locked_percent)

    def _check_trailing_stop(self, position: Position) -> PositionExitDecision:
        required_net_profit_percent = self._required_net_profit_percent(position)
        minimum_profitable_price = self._minimum_profitable_exit_price(position)
        net_pnl_percent = self.calculator.calculate(position, position.current_price).net_pnl_percent
        if net_pnl_percent < required_net_profit_percent:
            return PositionExitDecision(False, PositionExitReason.NONE, position.current_price,
                                        f"TRAILING_WAIT_NET_PROFIT:{net_pnl_percent:.3f}%<{required_net_profit_percent:.3f}%")
        atr_percent = self._get_atr_percent(position.symbol)
        if atr_percent is None or atr_percent <= 0:
            atr_percent = 0.40
        distance = atr_percent * self.trailing_atr_multiplier
        raw_trailing_price = position.highest_price * (1 - distance / 100.0)
        trailing_take_profit_percent = self._trailing_take_profit_floor_percent(position, required_net_profit_percent)
        trailing_take_profit_price = self._price_for_net_profit_percent(position, trailing_take_profit_percent)
        if trailing_take_profit_percent > required_net_profit_percent:
            trailing_price = max(minimum_profitable_price, min(raw_trailing_price, trailing_take_profit_price))
        else:
            trailing_price = max(raw_trailing_price, minimum_profitable_price)
        if position.current_price <= trailing_price and position.current_price < position.highest_price:
            peak_net_profit_percent = self.calculator.calculate(position, position.highest_price).net_pnl_percent
            lock_active = trailing_take_profit_percent > required_net_profit_percent
            return PositionExitDecision(True, PositionExitReason.TRAILING_STOP, position.current_price,
                                        "Fee-aware Adaptive Trailing Take Profit "
                                        f"(ATR: {atr_percent:.2f}%, Distance: {distance:.2f}%, "
                                        f"Required Net: {required_net_profit_percent:.2f}%, "
                                        f"Peak Net: {peak_net_profit_percent:.2f}%, "
                                        f"Locked Net: {trailing_take_profit_percent:.2f}%, "
                                        f"TP Trail: {'ACTIVE' if lock_active else 'ARMING'}, "
                                        f"R:R: {self.reward_to_risk_ratio:.2f})")
        return PositionExitDecision(False, PositionExitReason.NONE)

    def _check_review_required(self, position: Position) -> PositionExitDecision:
        if position.status != PositionStatus.HOLD or position.entered_hold_at is None:
            return PositionExitDecision(False, PositionExitReason.NONE)
        days = (time.time() - position.entered_hold_at) / 86400.0
        if days >= self.max_holding_days:
            if position.status != PositionStatus.REVIEW_REQUIRED:
                position.status = PositionStatus.REVIEW_REQUIRED
                position.review_required_at = time.time()
                self._review_decisions.append({"symbol": position.symbol, "holding_days": days,
                                               "pnl_percent": self._get_pnl_percent(position),
                                               "timestamp": time.time()})
            return PositionExitDecision(False, PositionExitReason.REVIEW_REQUIRED,
                                        position.current_price, f"Review required after {days:.1f} days",
                                        review_required=True)
        return PositionExitDecision(False, PositionExitReason.NONE)

    def _get_atr_percent(self, symbol: str) -> Optional[float]:
        if not self.atr_provider:
            return None
        try:
            value = self.atr_provider(symbol)
            if isinstance(value, dict):
                value = value.get("percent", value.get("atr_percent"))
            return float(value) if value is not None else None
        except (TypeError, ValueError, Exception):
            return None

    @staticmethod
    def _get_pnl_percent(position: Position) -> float:
        return (position.current_price - position.entry_price) / position.entry_price * 100.0

    def _is_profitable(self, position: Position) -> bool:
        return self._get_pnl_percent(position) > 0
