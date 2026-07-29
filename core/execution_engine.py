from dataclasses import dataclass
from datetime import datetime, timezone

from core.models import (
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


@dataclass
class ExecutionResult:
    """
    نتيجة تنفيذ الصفقة.
    """

    success: bool

    message: str

    symbol: str

    signal: TradeSignal

    trade_type: TradeType | None

    quantity: float

    entry_price: float

    stop_loss: float

    take_profit: float

    confidence: float

    execution_time: datetime


class ExecutionEngine:
    """
    مسؤول عن تنفيذ قرارات التداول.

    لا يحسب المؤشرات.

    لا يحسب المخاطرة.

    وإنما يستقبل القرار النهائي
    ثم ينفذه.
    """

    def __init__(

        self,

        portfolio: PortfolioEngine,

        risk_engine: RiskEngine,

    ):

        self.portfolio = portfolio

        self.risk_engine = risk_engine

    # ==========================================================
    # Execute
    # ==========================================================

    def execute(

        self,

        symbol,

        current_price,

        decision: StrategyDecision,

    ):

        if decision.signal != TradeSignal.BUY:

            return ExecutionResult(

                success=False,

                message="NO_BUY_SIGNAL",

                symbol=symbol,

                signal=decision.signal,

                trade_type=None,

                quantity=0,

                entry_price=0,

                stop_loss=0,

                take_profit=0,

                confidence=decision.confidence,

                execution_time=datetime.now(
                    timezone.utc,
                ),

            )

        if self.portfolio.has_position(

            symbol

        ):

            return ExecutionResult(

                success=False,

                message="POSITION_ALREADY_EXISTS",

                symbol=symbol,

                signal=TradeSignal.HOLD,

                trade_type=None,

                quantity=0,

                entry_price=0,

                stop_loss=0,

                take_profit=0,

                confidence=0,

                execution_time=datetime.now(
                    timezone.utc,
                ),

            )

    # ==========================================================
    # POSITION SIZE
    # ==========================================================

    def _calculate_quantity(

        self,

        symbol,

        entry_price,

        stop_loss,

    ):

        capital = self.portfolio.balance

        position_size = (

            self.risk_engine.calculate_position_size(

                capital=capital,

                entry_price=entry_price,

                stop_loss=stop_loss,

            )

        )

        quantity = (

            position_size

            /

            entry_price

        )

        return max(

            quantity,

            0.0,

        )

    # ==========================================================
    # RECOVERY COINS
    # ==========================================================

    @staticmethod
    def recovery_allowed(

        symbol,

    ):

        recovery_symbols = {

            "BTCUSDT",

            "ETHUSDT",

            "BNBUSDT",

            "SOLUSDT",

        }

        return symbol in recovery_symbols

    # ==========================================================
    # OPEN POSITION
    # ==========================================================

    def open_position(

        self,

        symbol,

        current_price,

        decision,

    ):

        quantity = self._calculate_quantity(

            symbol,

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

                quantity=0,

                entry_price=0,

                stop_loss=0,

                take_profit=0,

                confidence=decision.confidence,

                execution_time=datetime.now(

                    timezone.utc,

                ),

            )

        self.portfolio.open_position(

            symbol=symbol,

            quantity=quantity,

            entry_price=current_price,

            atr_stop=decision.stop_loss,

        )

        position = self.portfolio.get_position(

            symbol,

        )

        position.trailing_active = False

        position.recovery_mode = (

            self.recovery_allowed(

                symbol,

            )

        )

        position.highest_price = (

            current_price

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
    # UPDATE OPEN POSITION
    # ==========================================================

    def update_position(

        self,

        symbol,

        current_price,

    ):

        position = self.portfolio.get_position(

            symbol,

        )

        if position is None:

            return None

        self.portfolio.update_highest_price(

            symbol,

            current_price,

        )

        # --------------------------------------------------
        # Activate Trailing Stop
        # --------------------------------------------------

        if (

            not position.trailing_active

            and

            current_price

            >=

            position.entry_price * 1.02

        ):

            position.trailing_active = True

        # --------------------------------------------------
        # Trailing Stop Exit
        # --------------------------------------------------

        if position.trailing_active:

            trailing_stop = (

                position.highest_price

                * 0.995

            )

            if current_price <= trailing_stop:

                return self.close_position(

                    symbol,

                    current_price,

                    "TRAILING_STOP",

                )

        # --------------------------------------------------
        # Take Profit
        # --------------------------------------------------

        if (

            hasattr(

                position,

                "take_profit",

            )

            and

            position.take_profit > 0

            and

            current_price

            >=

            position.take_profit

        ):

            return self.close_position(

                symbol,

                current_price,

                "TAKE_PROFIT",

            )

        # --------------------------------------------------
        # Stop Loss
        # --------------------------------------------------

        if (

            hasattr(

                position,

                "stop_loss",

            )

            and

            position.stop_loss > 0

            and

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
    # CLOSE POSITION
    # ==========================================================

    def close_position(

        self,

        symbol,

        current_price,

        reason,

    ):

        pnl = self.portfolio.close_position(

            symbol=symbol,

            exit_price=current_price,

            fees=0,

            exit_reason=reason,

            strategy_version="V3",

            run_id="LIVE",

        )

        return pnl

    # ==========================================================
    # EXECUTE DECISION
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

        return self.open_position(

            symbol,

            current_price,

            decision,

        )
