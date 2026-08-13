"""8.3 - Spot P&L, fees and break-even calculations."""
from dataclasses import dataclass
from .models import Position


@dataclass(slots=True)
class PositionCalculationResult:
    market_value: float
    cost_value: float
    gross_pnl: float
    gross_pnl_percent: float
    net_pnl: float
    net_pnl_percent: float
    entry_fee: float
    exit_fee: float
    total_fees: float
    break_even_price: float
    roi: float


class PositionCalculator:
    def __init__(self, entry_fee_rate: float = 0.001, exit_fee_rate: float = 0.001):
        if not 0 <= entry_fee_rate < 1 or not 0 <= exit_fee_rate < 1:
            raise ValueError("fee rates must be in [0, 1)")
        self.entry_fee_rate = entry_fee_rate
        self.exit_fee_rate = exit_fee_rate

    def calculate(self, position: Position, exit_price: float | None = None) -> PositionCalculationResult:
        price = position.current_price if exit_price is None else exit_price
        if price <= 0:
            raise ValueError("exit price must be positive")
        cost = position.quantity * position.entry_price
        value = position.quantity * price
        entry_fee = cost * self.entry_fee_rate
        exit_fee = value * self.exit_fee_rate
        gross = value - cost
        net = gross - entry_fee - exit_fee
        gross_pct = gross / cost * 100.0 if cost else 0.0
        net_pct = net / cost * 100.0 if cost else 0.0
        return PositionCalculationResult(
            market_value=value, cost_value=cost, gross_pnl=gross,
            gross_pnl_percent=gross_pct, net_pnl=net, net_pnl_percent=net_pct,
            entry_fee=entry_fee, exit_fee=exit_fee,
            total_fees=entry_fee + exit_fee,
            break_even_price=self._calculate_break_even(position.entry_price),
            roi=net_pct,
        )

    def _calculate_break_even(self, entry_price: float) -> float:
        # Solves: sell_value*(1-exit_fee) = buy_cost*(1+entry_fee).
        return entry_price * (1 + self.entry_fee_rate) / (1 - self.exit_fee_rate)

    def break_even_price(self, position: Position) -> float:
        return self._calculate_break_even(position.entry_price)

    def unrealized_pnl(self, position: Position) -> float:
        return self.calculate(position).net_pnl
