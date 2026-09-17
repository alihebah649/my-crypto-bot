"""Side-by-side replay helper for Legacy vs Entry v2.

No exchange calls, persistence writes, or trade execution are performed here.
The helper accepts already-recorded legacy strategy observations and the
corresponding market facts, then returns an auditable comparison row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .entry_v2_adapter import EntryV2MarketFacts, evaluate_legacy_with_entry_v2


@dataclass(frozen=True)
class ReplayRow:
    symbol: str
    legacy_decision: str
    legacy_trade_mode: str
    legacy_score: float | None
    v2_decision: str
    v2_trade_mode: str
    v2_setup_type: str | None
    v2_failed_gate: str | None
    v2_passed_gates: tuple[str, ...]
    candle_patterns_5m: tuple[str, ...]
    candle_patterns_15m: tuple[str, ...]
    candle_patterns_1h: tuple[str, ...]
    candle_patterns_4h: tuple[str, ...]


def _patterns(facts: EntryV2MarketFacts, timeframe: str) -> tuple[str, ...]:
    from .entry_v2_adapter import build_entry_scenario

    scenario = build_entry_scenario(facts)
    values = scenario["structure"]["multi_candle_by_timeframe"].get(timeframe, {}).get("patterns", ())
    return tuple(str(value) for value in values)


def replay_one(symbol: str, facts: EntryV2MarketFacts) -> ReplayRow:
    legacy: Mapping[str, Any] = facts.legacy_result
    decision = evaluate_legacy_with_entry_v2(facts)
    return ReplayRow(
        symbol=symbol,
        legacy_decision="BUY" if str(legacy.get("trade_mode", "NONE")).upper() in {"SCALP", "SWING"} and str(legacy.get("signal", "HOLD")).upper() == "BUY" else "HOLD",
        legacy_trade_mode=str(legacy.get("trade_mode", "NONE")).upper(),
        legacy_score=float(legacy["score"]) if legacy.get("score") is not None else None,
        v2_decision=decision.decision,
        v2_trade_mode=decision.trade_mode,
        v2_setup_type=decision.setup_type,
        v2_failed_gate=decision.failed_gate,
        v2_passed_gates=decision.passed_gates,
        candle_patterns_5m=_patterns(facts, "5m"),
        candle_patterns_15m=_patterns(facts, "15m"),
        candle_patterns_1h=_patterns(facts, "1h"),
        candle_patterns_4h=_patterns(facts, "4h"),
    )


def replay_many(cases: Mapping[str, EntryV2MarketFacts]) -> list[ReplayRow]:
    return [replay_one(symbol, facts) for symbol, facts in cases.items()]
