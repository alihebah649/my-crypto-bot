"""Part-6 risk gateway used by the application composition layer."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional, Protocol
from .integration_contracts import RiskSizingApproval, RiskSizingRequest
from .part6_risk import MarketContext, PositionSizeCalculator, RiskController, RiskDecision, RiskRejectReason, SymbolExposure

class PortfolioSnapshotProvider(Protocol):
    def snapshot(self) -> Any: ...
class MarketContextProvider(Protocol):
    def get_context(self, symbol: str) -> MarketContext: ...
class SymbolExposureProvider(Protocol):
    def get_exposure(self, symbol: str) -> Optional[SymbolExposure]: ...

@dataclass(slots=True)
class CoreRiskGateway:
    controller: RiskController
    position_sizer: PositionSizeCalculator
    portfolio_provider: PortfolioSnapshotProvider
    market_provider: MarketContextProvider
    exposure_provider: Optional[SymbolExposureProvider] = None
    quantity_normalizer: Any = None

    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval:
        try:
            if request.leverage != 1.0: return self._reject("LEVERAGE_NOT_ALLOWED_SPOT")
            if request.account_equity <= 0 or request.free_balance <= 0: return self._reject("INVALID_ACCOUNT")
            if request.entry_price <= 0 or request.stop_loss <= 0: return self._reject("INVALID_MARKET_DATA")
            if request.entry_price == request.stop_loss: return self._reject("INVALID_STOP_DISTANCE")
            portfolio = self.portfolio_provider.snapshot()
            market = self.market_provider.get_context(request.symbol)
            exposure = self.exposure_provider.get_exposure(request.symbol) if self.exposure_provider is not None else None
            gate = self.controller.evaluate(account=portfolio, symbol=request.symbol, signal=None, market=market, symbol_exposure=exposure)
            if gate.decision is not RiskDecision.APPROVED:
                return self._reject(gate.reject_reason.name, metadata=gate.metadata)

            config = self.position_sizer.config.position_sizing
            sizing = self.position_sizer.calculate(
                account_equity=request.account_equity,
                entry_price=request.entry_price,
                stop_loss=request.stop_loss,
                leverage=1.0,
                target_position_value=config.target_position_value,
            )
            quantity = sizing.quantity
            if self.quantity_normalizer is not None:
                quantity = float(self.quantity_normalizer.normalize(symbol=request.symbol, quantity=quantity, price=request.entry_price))
            if quantity <= 0: return self._reject("INVALID_POSITION_SIZE")
            position_value = quantity * request.entry_price
            if position_value < config.minimum_position_size: return self._reject("POSITION_TOO_SMALL")
            if position_value > config.maximum_position_size: return self._reject("MAX_POSITION_EXCEEDED")
            equity = max(float(portfolio.account_equity), 0.0)
            current_exposure = max(float(portfolio.used_margin), 0.0)
            max_exposure = equity * config_for_exposure(self.position_sizer.config) / 100.0
            prospective_exposure = current_exposure + position_value
            sizing_metadata = {
                "target_position_value": float(config.target_position_value),
                "risk_position_value": float(sizing.position_value),
                "risk_quantity": float(sizing.quantity),
                "risk_amount": float(sizing.risk_amount),
                "stop_distance": float(sizing.stop_distance),
            }
            if prospective_exposure > max_exposure:
                return self._reject(RiskRejectReason.MAX_PORTFOLIO_EXPOSURE.name, metadata={
                    "current_exposure": current_exposure,
                    "position_value": position_value,
                    "prospective_exposure": prospective_exposure,
                    "max_exposure": max_exposure,
                    **sizing_metadata,
                })
            capital_required = position_value
            total_required = capital_required + max(request.estimated_fee, 0.0) + max(request.maintenance_margin, 0.0)
            if total_required > request.free_balance:
                return self._reject("INSUFFICIENT_BALANCE", metadata={
                    "capital_required": capital_required,
                    "estimated_fee": max(request.estimated_fee, 0.0),
                    "maintenance_margin": max(request.maintenance_margin, 0.0),
                    "free_balance": request.free_balance,
                    **sizing_metadata,
                })
            return RiskSizingApproval(
                approved=True, reason="APPROVED", quantity=quantity, position_value=position_value,
                capital_required=capital_required, risk_amount=sizing.risk_amount, stop_distance=sizing.stop_distance, leverage=1.0,
                metadata={
                    "risk_percent": config.risk_per_trade_percent,
                    "target_position_value": config.target_position_value,
                    "risk_position_value": sizing.position_value,
                    "source": "TradeManager.Part6",
                    "estimated_fee": max(request.estimated_fee, 0.0),
                },
            )
        except Exception as exc:
            return self._reject("RISK_GATE_ERROR", metadata={"error": str(exc)})

    @staticmethod
    def _reject(reason: str, metadata: Optional[dict[str, Any]] = None) -> RiskSizingApproval:
        return RiskSizingApproval(approved=False, reason=reason, metadata=dict(metadata or {}))

def config_for_exposure(config) -> float:
    return float(config.exposure.max_portfolio_exposure_percent)

__all__ = ["PortfolioSnapshotProvider", "MarketContextProvider", "SymbolExposureProvider", "CoreRiskGateway"]
