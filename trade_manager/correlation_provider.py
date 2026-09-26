"""Paper/runtime correlation provider backed by the canonical market-data cache.

This module only translates existing closed-candle cache data into the scalar
correlation score already supported by Trade Manager Part 6. It does not
introduce a new threshold or strategy rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import pandas as pd

from .models import PositionStatus
from .repository import PositionRepository


@dataclass(slots=True)
class KlineCorrelationProvider:
    repository: PositionRepository
    candle_loader: Callable[[str], Iterable[dict[str, Any]]]
    lookback_candles: int = 200
    minimum_observations: int = 30

    def get_score(self, symbol: str) -> float:
        target = str(symbol).upper()
        active_symbols = {
            str(position.symbol).upper()
            for position in self.repository.get_open_positions()
            if position.status in {
                PositionStatus.OPEN,
                PositionStatus.HOLD,
                PositionStatus.REVIEW_REQUIRED,
                PositionStatus.PARTIALLY_CLOSED,
            }
        }
        active_symbols.discard(target)
        if not active_symbols:
            return 0.0

        target_series = self._close_series(target)
        if target_series is None:
            return 0.0

        best_score = 0.0
        for other in sorted(active_symbols):
            other_series = self._close_series(other)
            if other_series is None:
                continue
            aligned = pd.concat(
                [target_series.rename("target"), other_series.rename("other")],
                axis=1,
                join="inner",
            ).dropna()
            if len(aligned) < self.minimum_observations:
                continue
            returns = aligned.pct_change().dropna().tail(self.lookback_candles)
            if len(returns) < max(2, self.minimum_observations - 1):
                continue
            correlation = returns["target"].corr(returns["other"])
            if pd.isna(correlation):
                continue
            value = float(correlation)
            if abs(value) > abs(best_score):
                best_score = value

        return best_score

    def _close_series(self, symbol: str) -> pd.Series | None:
        try:
            rows = list(self.candle_loader(str(symbol).upper()) or [])
        except Exception:
            return None

        points: dict[int, float] = {}
        for row in rows:
            try:
                open_time = int(row.get("open_time"))
                close = float(row.get("close"))
            except (AttributeError, TypeError, ValueError):
                continue
            if open_time <= 0 or close <= 0:
                continue
            points[open_time] = close

        if len(points) < self.minimum_observations:
            return None

        index = sorted(points)
        return pd.Series([points[key] for key in index], index=index, dtype="float64")
