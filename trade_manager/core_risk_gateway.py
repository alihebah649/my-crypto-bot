"""Part-6 risk gateway used by the application composition layer.

This module is an adapter, not a second risk engine.  ``RiskController`` and
``PositionSizeCalculator`` remain the owners of Part-6 decisions and sizing.
The adapter only converts core/application snapshots into the Part-6 contract.

The gateway is fail-closed: missing or invalid account/market data produces a
rejection rather than silently inventing values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Optional

from .integration_contracts import RiskSizingApproval, RiskSizingRequest
from .part6_risk import (
    MarketContext,
    PositionSizeCalculator,
    RiskController,
    RiskDecision,
    SymbolExposure,
)


class PortfolioSnapshotProvider(Protocol):
    """Supplies the canonical core portfolio snapshot."""

    def snapshot(self) -> Any:
        ...


class MarketContextProvider(Protocol):
    """Supplies a Part-6-compatible market context for one symbol."""

    def get_context(self, symbol: str) -> MarketContext:
        ...


class SymbolExposureProvider(Protocol):
    """Optional provider for current symbol exposure."""

    def get_exposure(self, symbol: str) -> Optional[SymbolExposure]:
        ...


@dataclass(slots=True)
class CoreRiskGateway:
    """Concrete ``RiskGateway`` backed by the existing Part-6 components."""

    controller: RiskController
    position_sizer: PositionSizeCalculator
    portfolio_provider: PortfolioSnapshotProvider
    market_provider: MarketContextProvider
    exposure_provider: Optional[SymbolExposureProvider] = None
    quantity_normalizer: Any = None

    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval:
        try:
            if request.leverage != 1.0:
                return self._reject("LEVERAGE_NOT_ALLOWED_SPOT")
            if request.account_equity <= 0 or request.free_balance <= 0:
                return self._reject("INVALID_ACCOUNT")
            if request.entry_price <= 0 or request.stop_loss <= 0:
                return self._reject("INVALID_MARKET_DATA")
            if request.entry_price == request.stop_loss:
                return self._reject("INVALID_STOP_DISTANCE")

            portfolio = self.portfolio_provider.snapshot()
            market = self.market_provider.get_context(request.symbol)
            exposure = (
                self.exposure_provider.get_exposure(request.symbol)
                if self.exposure_provider is not None
                else None
            )

            gate = self.controller.evaluate(
                account=portfolio,
                symbol=request.symbol,
                signal=None,
                market=market,
                symbol_exposure=exposure,
            )
            if gate.decision is not RiskDecision.APPROVED:
                return self._reject(
                    gate.reject_reason.name,
                    metadata=gate.metadata,
                )

            sizing = self.position_sizer.calculate(
                account_equity=request.account_equity,
                entry_price=request.entry_price,
                stop_loss=request.stop_loss,
                leverage=1.0,
            )

            quantity = sizing.quantity
            if self.quantity_normalizer is not None:
                quantity = float(
                    self.quantity_normalizer.normalize(
                        symbol=request.symbol,
                        quantity=quantity,
                        price=request.entry_price,
                    )
                )

            if quantity <= 0:
                return self._reject("INVALID_POSITION_SIZE")

            position_value = quantity * request.entry_price
            capital_required = position_value
            if capital_required > request.free_balance:
                return self._reject("INSUFFICIENT_BALANCE")

            return RiskSizingApproval(
                approved=True,
                reason="APPROVED",
                quantity=quantity,
                position_value=position_value,
                capital_required=capital_required,
                risk_amount=sizing.risk_amount,
                stop_distance=sizing.stop_distance,
                leverage=1.0,
                metadata={
                    "risk_percent": self.position_sizer.config.position_sizing.risk_per_trade_percent,
                    "source": "TradeManager.Part6",
                },
            )
        except Exception as exc:
            return self._reject(
                "RISK_GATE_ERROR",
                metadata={"error": str(exc)},
            )

    @staticmethod
    def _reject(reason: str, metadata: Optional[dict[str, Any]] = None) -> RiskSizingApproval:
        return RiskSizingApproval(
            approved=False,
            reason=reason,
            metadata=dict(metadata or {}),
        )


__all__ = [
    "PortfolioSnapshotProvider",
    "MarketContextProvider",
    "SymbolExposureProvider",
    "CoreRiskGateway",
]
