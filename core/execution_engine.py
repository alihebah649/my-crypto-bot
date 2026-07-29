from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.models import (
    Position,
    PositionRuntime,
    TradeSignal,
    TradeType,
)

from core.strategy_engine import (
    StrategyDecision,
)

from core.portfolio_engine import (
    PortfolioEngine,
)

from core.risk_engine import (
    RiskEngine,
)


# ==========================================================
# Execution Result
# ==========================================================

@dataclass
class ExecutionResult:

    success: bool

    message: str

    symbol: str

    signal: TradeSignal

    trade_type: Optional[TradeType]

    quantity: float

    entry_price: float

    stop_loss: float

    take_profit: float

    confidence: float

    execution_time: datetime


# ==========================================================
# Execution Engine
# ==========================================================

class ExecutionEngine:

    """
    مسؤول عن تنفيذ قرارات التداول
    وإدارة الصفقات المفتوحة.
    """

    def __init__(

        self,

        portfolio: PortfolioEngine,

        risk_engine: RiskEngine,

    ):

        self.portfolio = portfolio

        self.risk_engine = risk_engine

    # ==========================================================
    # Recovery Coins
    # ==========================================================

    RECOVERY_SYMBOLS = {

        "BTCUSDT",

        "ETHUSDT",

        "BNBUSDT",

        "SOLUSDT",

    }

    # ==========================================================
    # Helpers
    # ==========================================================

    @staticmethod
    def recovery_allowed(

        symbol: str,

    ) -> bool:

        return (

            symbol

            in

            ExecutionEngine.RECOVERY_SYMBOLS

        )

    # ==========================================================
    # Position Size
    # ==========================================================

    def calculate_quantity(

        self,

        capital: float,

        entry_price: float,

        stop_loss: float,

    ) -> float:

        position_value = (

            self.risk_engine.calculate_position_size(

                capital=capital,

                entry_price=entry_price,

                stop_loss=stop_loss,

            )

        )

        if position_value <= 0:

            return 0.0

        return (

            position_value

            /

            entry_price

        )

    # ==========================================================
    # Split Position
    # ==========================================================

    def split_position(

        self,

        quantity: float,

        trade_type: TradeType,

    ):

        if trade_type == TradeType.SCALPING:

            return (

                quantity,

                0.0,

            )

        if trade_type == TradeType.SWING:

            return (

                0.0,

                quantity,

            )

        return (

            quantity * 0.40,

            quantity * 0.60,

        )

    # ==========================================================
    # Build Position
    # ==========================================================

    def build_position(

        self,

        symbol: str,

        decision: StrategyDecision,

        quantity: float,

        entry_price: float,

    ) -> Position:

        scalp_qty, swing_qty = self.split_position(

            quantity,

            decision.trade_type,

        )

        position = Position(

            symbol=symbol,

            quantity=quantity,

            entry_price=entry_price,

            highest_price=entry_price,

            stop_loss=decision.stop_loss,

            take_profit=decision.take_profit,

            atr_stop=decision.stop_loss,

            confidence=decision.confidence,

            trade_type=decision.trade_type,

            recovery_mode=self.recovery_allowed(

                symbol,

            ),

        )

        runtime = PositionRuntime()

        runtime.scalp_quantity = scalp_qty

        runtime.swing_quantity = swing_qty

        runtime.remaining_quantity = quantity

        runtime.last_price = entry_price

        runtime.trailing_stop_price = (

            decision.stop_loss

        )

        position.runtime = runtime

        return position

    # ==========================================================
    # Open Position
    # ==========================================================

    def open_position(

        self,

        symbol: str,

        current_price: float,

        decision: StrategyDecision,

    ) -> ExecutionResult:

        capital = self.portfolio.balance

        quantity = self.calculate_quantity(

            capital,

            current_price,

            decision.stop_loss,

        )

        if quantity <= 0:

            return ExecutionResult(

                success=False,

                message="INVALID_POSITION_SIZE",

                symbol=symbol,

                signal=TradeSignal.HOLD,

                trade_type=None,

                quantity=0.0,

                entry_price=0.0,

                stop_loss=0.0,

                take_profit=0.0,

                confidence=decision.confidence,

                execution_time=datetime.now(

                    timezone.utc,

                ),

            )

        position = self.build_position(

            symbol,

            decision,

            quantity,

            current_price,

        )

        self.portfolio.open_position(

            symbol=position.symbol,

            quantity=position.quantity,

            entry_price=position.entry_price,

            atr_stop=position.atr_stop,

        )

        stored = self.portfolio.get_position(

            symbol,

        )

        stored.stop_loss = (

            position.stop_loss

        )

        stored.take_profit = (

            position.take_profit

        )

        stored.trade_type = (

            position.trade_type

        )

        stored.confidence = (

            position.confidence

        )

        stored.recovery_mode = (

            position.recovery_mode

        )

        stored.runtime = (

            position.runtime

        )

        return ExecutionResult(

            success=True,

            message="POSITION_OPENED",

            symbol=symbol,

            signal=TradeSignal.BUY,

            trade_type=decision.trade_type,

            quantity=quantity,

            entry_price=current_price,

            stop_loss=decision.stop_loss,

            take_profit=decision.take_profit,

            confidence=decision.confidence,

            execution_time=datetime.now(

                timezone.utc,

            ),

        )

    # ==========================================================
    # Update Position
    # ==========================================================

    def update_position(

        self,

        symbol: str,

        current_price: float,

    ):

        position = self.portfolio.get_position(

            symbol,

        )

        if position is None:

            return None

        runtime = position.runtime

        runtime.last_price = current_price

        # -----------------------------------------
        # Highest Price
        # -----------------------------------------

        if current_price > position.highest_price:

            position.highest_price = current_price

        # -----------------------------------------
        # Unrealized Profit
        # -----------------------------------------

        runtime.unrealized_profit = (

            current_price

            -

            position.entry_price

        ) * position.quantity

        profit_percent = (

            (

                current_price

                -

                position.entry_price

            )

            /

            position.entry_price

        ) * 100

        runtime.highest_profit_percent = max(

            runtime.highest_profit_percent,

            profit_percent,

        )

        # -----------------------------------------
        # Break Even
        # -----------------------------------------

        if (

            not runtime.break_even_enabled

            and

            profit_percent >= 2.0

        ):

            runtime.break_even_enabled = True

            runtime.break_even_price = (

                position.entry_price

            )

            position.stop_loss = (

                position.entry_price

            )

        # -----------------------------------------
        # Trailing Stop
        # -----------------------------------------

        if profit_percent >= 3:

            trailing = (

                position.highest_price

                * 0.995

            )

            if (

                trailing

                >

                runtime.trailing_stop_price

            ):

                runtime.trailing_stop_price = (

                    trailing

                )

        if (

            runtime.trailing_stop_price > 0

            and

            current_price

            <=

            runtime.trailing_stop_price

        ):

            return self.close_position(

                symbol,

                current_price,

                "TRAILING_STOP",

            )

        # -----------------------------------------
        # Take Profit
        # -----------------------------------------

        if (

            current_price

            >=

            position.take_profit

        ):

            return self.close_position(

                symbol,

                current_price,

                "TAKE_PROFIT",

            )

        # -----------------------------------------
        # Stop Loss
        # -----------------------------------------

        if (

            current_price

            <=

            position.stop_loss

        ):

            if position.recovery_mode:

                return None

            return self.close_position(

                symbol,

                current_price,

                "STOP_LOSS",

            )

        return None

    # ==========================================================
    # Close Position
    # ==========================================================

    def close_position(

        self,

        symbol,

        exit_price,

        reason,

    ):

        return self.portfolio.close_position(

            symbol=symbol,

            exit_price=exit_price,

            fees=0.0,

            exit_reason=reason,

            strategy_version="Shadow_V3",

            run_id="LIVE",

        )

    # ==========================================================
    # Process
    # ==========================================================

    def process(

        self,

        symbol,

        current_price,

        decision,

    ):

        if self.portfolio.has_position(

            symbol,

        ):

            return self.update_position(

                symbol,

                current_price,

            )

        if decision.signal != TradeSignal.BUY:

            return None

        return self.open_position(

            symbol,

            current_price,

            decision,

        )
        
