"""Entry v2 decision contract.

This module is intentionally isolated from the live runtime. It evaluates
already-derived market facts and returns a deterministic decision trace.
The legacy score is diagnostic only; it can never override a failed hard gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EntryDecision:
    approved: bool
    decision: str
    trade_mode: str
    setup_type: str | None
    failed_gate: str | None = None
    passed_gates: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class EntryEngineV2:
    """Pure, side-effect-free Entry v2 gate engine.

    Score is diagnostic only. Entry authorization comes from hard gates.
    """

    MAX_STOP_DISTANCE_PERCENT = 3.0
    MIN_REWARD_RISK = 1.0
    MAX_SPREAD_PERCENT = 0.15

    def evaluate(self, scenario: Any) -> EntryDecision:
        market = self._mapping(scenario, "market")
        structure = self._mapping(scenario, "structure")
        trigger = self._mapping(scenario, "trigger")
        execution = self._mapping(scenario, "execution")
        risk = self._mapping(scenario, "risk")
        metadata = self._mapping(scenario, "metadata")
        mode = str(getattr(scenario, "trade_mode", "SCALP") or "SCALP").upper()
        requested_setup = getattr(scenario, "setup_type", None)

        passed: list[str] = []

        if execution.get("closed_candle") is not True:
            return self._reject(mode, requested_setup, "REJECT_DATA_UNAVAILABLE", "CLOSED_CANDLE_REQUIRED", passed)
        passed.append("DATA_READY")

        if str(market.get("btc_guard", "PASS")).upper() != "PASS":
            return self._reject(mode, requested_setup, "REJECT_BTC_GUARD", "BTC_GUARD_FAILED", passed)
        passed.append("BTC_GUARD_PASS")

        prior_exit = metadata.get("prior_exit")
        same_context = bool(metadata.get("prior_context_fingerprint_same"))
        new_structure = bool(structure.get("new_structure_after_prior_stop"))
        if prior_exit == "STOP_LOSS" and same_context and not new_structure:
            return self._reject(mode, requested_setup, "REJECT_REENTRY_LOCK", "SAME_CONTEXT_AFTER_STOP", passed)
        passed.append("REENTRY_CHECK")

        higher_bearish = all(
            str(market.get(tf, "NEUTRAL")).upper() == "BEARISH"
            for tf in ("15m_bias", "1h_bias", "4h_bias")
        )
        weak_recovery = str(market.get("5m_bias", "")).upper() == "RECOVERY" and not bool(
            trigger.get("confirmed_reversal")
        )
        if higher_bearish and weak_recovery:
            return self._reject(mode, requested_setup, "REJECT_COUNTERTREND", "WEAK_RECOVERY_AGAINST_HTF_BEARISH", passed)
        passed.append("REGIME_ALLOWED")

        has_location = bool(structure.get("location_at_support") or structure.get("location_pullback"))
        if not has_location:
            return self._reject(mode, requested_setup, "REJECT_NO_LOCATION", "NO_VALID_ENTRY_LOCATION", passed)
        passed.append("LOCATION_VALID")

        continuation = bool(structure.get("continuation_break") and structure.get("pullback_holds"))
        seller_failure = bool(structure.get("selling_pressure_weakening"))
        if mode == "SCALP" and not seller_failure and not continuation:
            return self._reject(mode, requested_setup, "REJECT_NO_SELLER_FAILURE", "SELLER_PRESSURE_NOT_INVALIDATED", passed)
        passed.append("SELLER_FAILURE_OR_CONTINUATION")

        reclaim = bool(structure.get("reclaim"))
        higher_low = bool(structure.get("higher_low"))
        confirmed_reversal = bool(trigger.get("confirmed_reversal"))
        if continuation:
            structure_valid = True
            setup_type = "CONTINUATION"
        else:
            structure_valid = reclaim and higher_low and confirmed_reversal
            setup_type = "REVERSAL"
        if not structure_valid:
            return self._reject(mode, requested_setup, "REJECT_NO_RECLAIM", "STRUCTURAL_RECLAIM_NOT_CONFIRMED", passed)
        passed.append("STRUCTURE_CONFIRMED")

        if bool(trigger.get("overextended")):
            return self._reject(mode, setup_type, "REJECT_OVEREXTENDED", "PRICE_ALREADY_EXTENDED_FROM_ENTRY_LOCATION", passed)
        passed.append("EXTENSION_VALID")

        volume_ratio = self._float(trigger.get("volume_ratio_5m", 0.0))
        if mode == "SCALP" and volume_ratio < 1.0:
            return self._reject(mode, setup_type, "REJECT_NO_VOLUME_CONFIRM", "VOLUME_NOT_CONFIRMING", passed)
        passed.append("VOLUME_CONFIRMED")

        spread = self._float(execution.get("spread_percent", 0.0))
        if spread > self.MAX_SPREAD_PERCENT:
            return self._reject(mode, setup_type, "REJECT_DATA_UNAVAILABLE", "SPREAD_TOO_WIDE", passed)
        passed.append("EXECUTION_QUALITY")

        stop_distance = self._float(risk.get("stop_distance_percent", 999.0))
        if stop_distance <= 0 or stop_distance > self.MAX_STOP_DISTANCE_PERCENT:
            return self._reject(mode, setup_type, "REJECT_STOP_TOO_WIDE", "STOP_DISTANCE_OUT_OF_RANGE", passed)
        passed.append("STOP_WIDTH_VALID")

        reward_risk = self._float(risk.get("reward_risk", 0.0))
        if reward_risk < self.MIN_REWARD_RISK:
            return self._reject(mode, setup_type, "REJECT_LOW_REWARD", "REWARD_RISK_TOO_LOW", passed)
        passed.append("REWARD_RISK_VALID")

        return EntryDecision(
            approved=True,
            decision=f"APPROVED_{mode}",
            trade_mode=mode,
            setup_type=setup_type,
            passed_gates=tuple(passed),
            diagnostics={
                "legacy_score": metadata.get("legacy_score"),
                "legacy_score_used_as_gate": False,
                "volume_ratio_5m": volume_ratio,
                "stop_distance_percent": stop_distance,
                "reward_risk": reward_risk,
                "reentry_same_context": same_context,
            },
        )

    @staticmethod
    def _mapping(obj: Any, name: str) -> Mapping[str, Any]:
        value = getattr(obj, name, {})
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _reject(mode: str, setup_type: str | None, decision: str, reason: str, passed: list[str]) -> EntryDecision:
        return EntryDecision(
            approved=False,
            decision=decision,
            trade_mode=mode,
            setup_type=setup_type,
            failed_gate=reason,
            passed_gates=tuple(passed),
            reasons=(reason,),
            diagnostics={"legacy_score_used_as_gate": False},
        )


def evaluate_entry(scenario: Any) -> EntryDecision:
    return EntryEngineV2().evaluate(scenario)
