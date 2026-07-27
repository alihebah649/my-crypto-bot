from dataclasses import dataclass

from core.portfolio_engine import PortfolioEngine
from core.risk_engine import RiskEngine


@dataclass
class ExecutionResult:
    success: bool
    message: str
    amount: float = 0.0


class ExecutionEngine:

    def __init__(
        self,
        portfolio: PortfolioEngine,
        risk: RiskEngine,
    ):
        self.portfolio = portfolio
        self.risk = risk

    def execute_buy(
        self,
        symbol: str,
        price: float,
        atr: float,
    ) -> ExecutionResult:

        equity = self.portfolio.get_equity()

        exposure = self.portfolio.get_total_exposure()

        cash = self.portfolio.balance

        size = self.risk.calculate_position_size(
            equity=equity,
            cash=cash,
            current_exposure=exposure,
            entry_price=price,
            atr=atr,
        )

        if size <= 0:
            return ExecutionResult(
                False,
                "تعذر حساب حجم الصفقة.",
            )

        quantity = size / price

        success = self.portfolio.open_position(
            symbol=symbol,
            quantity=quantity,
            entry_price=price,
            atr_stop=self.risk.hard_stop_price(price, atr),
        )

        if not success:
            return ExecutionResult(
                False,
                "فشل فتح الصفقة.",
            )

        return ExecutionResult(
            True,
            f"تم شراء {symbol}",
            size,
        )

    def execute_sell(
        self,
        symbol: str,
        price: float,
    ) -> ExecutionResult:

        pnl = self.portfolio.close_position(
            symbol=symbol,
            exit_price=price,
        )

        if pnl is None:
            return ExecutionResult(
                False,
                "الصفقة غير موجودة.",
            )

        return ExecutionResult(
            True,
            f"تم إغلاق {symbol}",
            pnl,
        )
