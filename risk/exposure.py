from core.portfolio_engine import PortfolioState


class PortfolioExposure:
    """
    مسؤول عن حساب وإدارة التعرض الحالي للمحفظة.
    """

    def __init__(self, portfolio: PortfolioState):
        self.portfolio = portfolio

    # ---------------------------------------------------------

    def current_exposure(self) -> float:
        """
        إجمالي قيمة جميع المراكز المفتوحة.
        """

        exposure = 0.0

        for position in self.portfolio.open_positions.values():

            if position.is_open:

                exposure += (
                    position.quantity
                    * position.entry_price
                )

        return exposure

    # ---------------------------------------------------------

    def position_value(self, symbol: str) -> float:

        if symbol not in self.portfolio.open_positions:
            return 0.0

        p = self.portfolio.open_positions[symbol]

        if not p.is_open:
            return 0.0

        return p.quantity * p.entry_price

    # ---------------------------------------------------------

    def open_positions_count(self) -> int:

        return sum(
            1
            for p in self.portfolio.open_positions.values()
            if p.is_open
        )

    # ---------------------------------------------------------

    def has_position(self, symbol: str) -> bool:

        if symbol not in self.portfolio.open_positions:
            return False

        return self.portfolio.open_positions[symbol].is_open
