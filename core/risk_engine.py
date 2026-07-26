from dataclasses import dataclass


@dataclass
class RiskConfig:
    # نسبة المخاطرة من رأس المال في الصفقة الواحدة
    risk_per_trade: float = 0.01

    # أقصى نسبة يمكن استثمارها من كامل المحفظة
    max_portfolio_exposure: float = 0.25

    # أقصى نسبة للصفقة الواحدة
    max_position_size: float = 0.05

    # أقل قيمة للصفقة بالدولار
    min_position_size: float = 10.0

    # مضاعف ATR للستوب
    atr_multiplier: float = 2.0


class RiskEngine:

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()

    def calculate_position_size(
        self,
        equity: float,
        cash: float,
        current_exposure: float,
        entry_price: float,
        atr: float,
    ) -> float:
        """
        يحسب حجم الصفقة بالدولار.
        """

        if equity <= 0:
            return 0.0

        if atr is None or atr <= 0:
            return 0.0

        # المبلغ الذي نسمح بخسارته
        risk_amount = equity * self.config.risk_per_trade

        stop_distance = atr * self.config.atr_multiplier

        if stop_distance <= 0:
            return 0.0

        quantity = risk_amount / stop_distance

        position_value = quantity * entry_price

        # الحد الأقصى للصفقة الواحدة
        max_position = equity * self.config.max_position_size

        # الحد الأقصى للتعرض الكلي
        max_total = equity * self.config.max_portfolio_exposure

        remaining = max_total - current_exposure

        if remaining <= 0:
            return 0.0

        position_value = min(
            position_value,
            max_position,
            remaining,
            cash,
        )

        if position_value < self.config.min_position_size:
            return 0.0

        return round(position_value, 2)

    def hard_stop_price(self, entry_price: float, atr: float) -> float:
        """
        سعر وقف الخسارة الابتدائي.
        """
        return entry_price - (atr * self.config.atr_multiplier)

    def trailing_stop_price(
        self,
        highest_price: float,
        atr: float,
        multiplier: float = 2.5,
    ) -> float:
        """
        وقف الخسارة المتحرك.
        """
        return highest_price - (atr * multiplier)

    def can_open_new_trade(
        self,
        equity: float,
        current_exposure: float,
    ) -> bool:

        max_allowed = equity * self.config.max_portfolio_exposure

        return current_exposure < max_allowed

    def risk_percentage(self) -> float:
        return self.config.risk_per_trade * 100

    def max_exposure_percentage(self) -> float:
        return self.config.max_portfolio_exposure * 100
