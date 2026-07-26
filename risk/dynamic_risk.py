from dataclasses import dataclass


@dataclass
class RiskConfig:
    """
    إعدادات إدارة المخاطر.
    """

    account_balance: float = 10000.0

    risk_per_trade_pct: float = 0.0075

    max_portfolio_exposure_pct: float = 0.25

    atr_stop_multiplier: float = 2.0


class DynamicRiskEngine:
    """
    مسؤول عن:

    • حساب حجم الصفقة
    • إدارة نسبة المخاطرة
    • فحص التعرض الكلي للمحفظة
    """

    def __init__(self, config: RiskConfig):

        self.config = config

    # ---------------------------------------------------------

    def risk_amount(self):

        return (
            self.config.account_balance
            * self.config.risk_per_trade_pct
        )

    # ---------------------------------------------------------

    def calculate_position_size(
        self,
        entry_price: float,
        atr: float
    ) -> float:

        if atr <= 0:
            return 0.0

        stop_distance = (
            atr
            * self.config.atr_stop_multiplier
        )

        if stop_distance <= 0:
            return 0.0

        shares = self.risk_amount() / stop_distance

        position_value = shares * entry_price

        return position_value

    # ---------------------------------------------------------

    def max_allowed_exposure(self):

        return (
            self.config.account_balance
            * self.config.max_portfolio_exposure_pct
        )

    # ---------------------------------------------------------

    def exposure_allowed(
        self,
        current_exposure: float,
        new_position_value: float
    ) -> bool:

        total = current_exposure + new_position_value

        return total <= self.max_allowed_exposure()

    # ---------------------------------------------------------

    def update_balance(
        self,
        new_balance: float
    ):

        self.config.account_balance = new_balance
