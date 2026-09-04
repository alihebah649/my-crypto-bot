"""Orchestrate exchange-side protection after a filled Spot BUY.

This layer is deliberately separate from Strategy and Trade Manager.  It does
not choose exit levels; it receives them, submits exchange-side protection,
and requires positive exchange confirmation before reporting PROTECTED.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.binance_protection import BinanceSpotProtection, ProtectionRequest
from core.live_protection_gate import ProtectionState


@dataclass(frozen=True, slots=True)
class ProtectionFlowResult:
    state: ProtectionState
    confirmed: bool
    reason: str
    exchange_response: dict[str, Any] | None = None


class LiveProtectionFlow:
    """Safe orchestration boundary for live exchange protection."""

    def __init__(self, protection: BinanceSpotProtection, *, live_mode: bool) -> None:
        self._protection = protection
        self._live_mode = live_mode

    def protect_filled_buy(
        self,
        *,
        buy_filled: bool,
        request: ProtectionRequest,
    ) -> ProtectionFlowResult:
        if not self._live_mode:
            return ProtectionFlowResult(
                ProtectionState.PROTECTED,
                True,
                "PAPER_MODE_NO_LIVE_PROTECTION_REQUIRED",
            )

        if not buy_filled:
            return ProtectionFlowResult(
                ProtectionState.UNPROTECTED,
                False,
                "BUY_NOT_FILLED",
            )

        try:
            response = self._protection.place_sell_protection(request)
        except Exception as exc:
            return ProtectionFlowResult(
                ProtectionState.UNPROTECTED,
                False,
                f"PROTECTION_SUBMISSION_FAILED:{type(exc).__name__}",
            )

        try:
            orders = self._protection.open_protection_orders(request.symbol)
        except Exception as exc:
            return ProtectionFlowResult(
                ProtectionState.PROTECTING,
                False,
                f"PROTECTION_CONFIRMATION_FAILED:{type(exc).__name__}",
                response,
            )

        confirmed = BinanceSpotProtection.has_active_sell_protection(
            orders,
            quantity=request.quantity,
            stop_price=request.stop_price,
        )
        if not confirmed:
            return ProtectionFlowResult(
                ProtectionState.PROTECTING,
                False,
                "EXCHANGE_PROTECTION_NOT_CONFIRMED",
                response,
            )

        return ProtectionFlowResult(
            ProtectionState.PROTECTED,
            True,
            "EXCHANGE_PROTECTION_CONFIRMED",
            response,
        )
