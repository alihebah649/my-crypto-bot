from dataclasses import dataclass

from core.signal_engine import Signal
from core.portfolio_engine import PortfolioEngine
from risk.dynamic_risk import DynamicRiskEngine
from risk.exposure import PortfolioExposure
from risk.correlation_filter import RollingCorrelationFilter


@dataclass
class StrategyDecision:
    """
    النتيجة النهائية لقرار الاستراتيجية.
    """

    allowed: bool
    reason: str
    position_size: float = 0.0


class StrategyManager:
    """
    قائد الاستراتيجية.

    لا ينفذ أي صفقة بنفسه،
    وإنما ينسق بين جميع المحركات.
    """

    def __init__(
        self,
        portfolio: PortfolioEngine,
        risk_engine: DynamicRiskEngine,
        exposure: PortfolioExposure,
        correlation_filter: RollingCorrelationFilter,
    ):
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.exposure = exposure
        self.correlation_filter = correlation_filter
