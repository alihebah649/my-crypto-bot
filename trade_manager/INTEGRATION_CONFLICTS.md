# Trade Manager Integration Conflicts

This file records source-to-baseline conflicts that were resolved explicitly.
Nothing listed here is silently hidden inside implementation code.

## C-001 — Part 5 time exit vs Smart Hold

**Source:** Part 5 `ExitRules.check_time_stop()` describes a 24-hour time stop that closes a position. The source also contains a TIME_STOP exit reason. fileciteturn837file14

**Project contract:** losing positions are not automatically sold merely because a holding-time threshold was reached. The Part-8 contract uses `REVIEW_REQUIRED` for the time-based review path.

**Resolution:** keep the time threshold as a review signal, not an automatic sell. The canonical protection evaluator returns `REVIEW_REQUIRED` when the position is still losing after the configured review period.

**Status:** RESOLVED.

## C-002 — Short-side formulas in Part 5 vs spot-only system

**Source:** the source PnL implementation contains both BUY and SELL branches. fileciteturn836file12

**Project contract:** the current bot is Spot-only and does not open short positions.

**Resolution:** canonical Part-8 position creation is `LONG` only. No short position is created by the Trade Manager boundary. The historical SELL branch is retained as source documentation, not as an active entry path.

**Status:** RESOLVED.

## C-003 — Part 7 Binance implementation is a skeleton

**Source:** Part 7 explicitly leaves submit/query/cancel/response parsing methods as `NotImplementedError`. fileciteturn836file4

**Resolution:** Part 7 remains a broker-neutral contract. The live/paper broker is injected through the execution pipeline; Trade Manager does not bypass that boundary.

**Status:** RESOLVED for architecture; live Binance execution remains a separate implementation task.

## C-004 — Duplicate position models between Parts 1–7 and Part 8

**Source:** the original Part 1 defines its own Trade/TradeContext-oriented lifecycle model. fileciteturn837file2

**Resolution:** Part 8 owns the canonical persisted Spot `Position` lifecycle. Parts 1–7 are compatibility boundaries and adapters; they do not create a second authoritative position repository.

**Status:** RESOLVED.

## C-005 — Part 6 sizing semantics

**Source:** Part 6 contains a calculator, exchange quantity normalization, funding validation and advanced capital validation as separate responsibilities.

**Resolution:** these responsibilities now live in `trade_manager/sizing.py`; the Part-6 boundary exports them while the Part-8 entry gate remains the canonical decision point.

**Status:** RESOLVED.
