"""Auditable, immutable record for one Brain shadow decision."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class BrainDecisionRecord:
    timestamp: float
    context_fingerprint: str
    symbol: str
    trade_mode: str
    brain_action: str
    confidence: float
    reason: str
    policy_action: Optional[str] = None
    final_action: Optional[str] = None
    authority: str = "POLICY"
    brain_agrees_with_policy: Optional[bool] = None
    exception: Optional[str] = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["BrainDecisionRecord"]
