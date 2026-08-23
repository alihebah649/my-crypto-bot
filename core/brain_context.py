"""Immutable context builder for the Shadow Trading Bot Brain.

The context layer is read-only. It gathers normalized market, position,
risk, and exit-policy facts for Brain reasoning without mutating trading state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class BrainContext:
    symbol: str
    trade_mode: str
    position_status: str
    current_price: float
    entry_price: float
    pnl_percent: float
    age_minutes: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    market: Mapping[str, Any] = field(default_factory=dict)
    risk: Mapping[str, Any] = field(default_factory=dict)
    recovery: Mapping[str, Any] = field(default_factory=dict)
    exit_policy: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrainContextBuilder:
    """Build a deterministic, read-only BrainContext from existing snapshots."""

    @staticmethod
    def _trade_mode(position: Any) -> str:
        entry_metadata = getattr(position, "entry_metadata", {}) or {}
        metadata = getattr(position, "metadata", {}) or {}
        return str(entry_metadata.get("trade_mode", metadata.get("trade_mode", "SWING"))).upper()

    @staticmethod
    def _status(position: Any) -> str:
        status = getattr(position, "status", "UNKNOWN")
        return getattr(status, "name", str(status)).upper()

    @staticmethod
    def build(
        position: Any,
        *,
        age_minutes: float = 0.0,
        market: Optional[Mapping[str, Any]] = None,
        risk: Optional[Mapping[str, Any]] = None,
        recovery: Optional[Mapping[str, Any]] = None,
        exit_policy: Optional[Mapping[str, Any]] = None,
    ) -> BrainContext:
        entry = float(getattr(position, "entry_price", 0.0) or 0.0)
        current = float(getattr(position, "current_price", 0.0) or 0.0)
        pnl = ((current - entry) / entry * 100.0) if entry > 0 else 0.0
        return BrainContext(
            symbol=str(getattr(position, "symbol", "")),
            trade_mode=BrainContextBuilder._trade_mode(position),
            position_status=BrainContextBuilder._status(position),
            current_price=current,
            entry_price=entry,
            pnl_percent=pnl,
            age_minutes=max(0.0, float(age_minutes)),
            stop_loss=getattr(position, "stop_loss", None),
            take_profit=getattr(position, "take_profit", None),
            market=dict(market or {}),
            risk=dict(risk or {}),
            recovery=dict(recovery or {}),
            exit_policy=dict(exit_policy or {}),
        )


__all__ = ["BrainContext", "BrainContextBuilder"]
