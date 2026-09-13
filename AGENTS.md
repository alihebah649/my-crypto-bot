# Shadow Trading Bot — Engineering Guardrails

## Mission

Stabilize and validate the existing Binance Spot paper-trading system before introducing new trading features. Prefer evidence from the repository, tests, runtime diagnostics, and production logs over assumptions.

## Non-negotiable trading constraints

- Spot trading only.
- No futures, leverage, margin, or short positions.
- SCALP entry threshold is 65 and must not be raised merely to reduce trade count.
- SWING entry threshold is 80.
- Do not make MACD or Stochastic mandatory filters unless the project owner explicitly changes this rule.
- Do not add strategy features just because they sound useful. First prove a real defect, measurable weakness, or missing safety control.

## Current development phase

The priority is stabilization, observability, and safe Paper Trading.

Before changing entry/exit strategy logic:
1. Map the actual execution path.
2. Identify the exact source of the behavior with code and runtime evidence.
3. Reproduce the issue where practical.
4. Add or improve diagnostics/tests if needed.
5. Make the smallest justified change.
6. Run relevant tests and inspect failures.
7. Compare behavior before and after the change.

Do not treat an undocumented or incomplete component as complete.

## Trade Manager warning

Trade Manager is not a single completed baseline file. It was designed as 12 parts. Parts 1–7 were prepared but were not necessarily integrated into a final file; Part 8 has been under review/integration and the available portion is Sections 8.1–8.8; Sections 9–12 are not assumed complete. Files under `core` were intended to interconnect with Trade Manager and the rest of the system, but compatibility must be audited rather than assumed.

Never describe Trade Manager as complete unless the repository proves that it is complete and integrated.

## Evidence discipline

Every important conclusion should be classified internally as one of:
- VERIFIED: directly confirmed by source code, test output, or runtime evidence.
- OBSERVED: seen in logs/diagnostics but not yet explained.
- INFERRED: plausible explanation that still needs confirmation.

Do not present an inference as a verified fact.

## Binance / market-data safety

- Treat Binance rate limits and 418/429 responses as production safety issues.
- Measure actual outbound Binance HTTP traffic before attributing rate-limit problems to a particular endpoint or request pattern.
- `X-MBX-USED-WEIGHT-1M` is an IP-level cumulative counter; request-level weight must not be inferred from a single header value without considering deltas and other traffic.
- Preserve the process-wide Binance circuit breaker unless a replacement is proven safer.
- Avoid unnecessary market-data polling.
- Do not increase request frequency to compensate for stale data without measuring the resulting request/weight impact.
- Keep market-data cache behavior and ticker grouping explicit and observable.

## Entry diagnostics

When investigating missing SCALP entries, inspect the complete path:
Market Data -> Indicators -> Strategy/Score -> SCALP gate -> Risk -> Existing Position -> Execution Adapter -> Position state.

A rejected entry must have an explicit reason. Do not assume that a low trade count means the score threshold is wrong.

## Paper vs live execution

- Current stabilization work must remain safe for Paper Trading.
- Paper execution must not accidentally send real exchange orders.
- Live execution paths must be clearly separated from Paper execution paths.
- Never enable live trading as part of a diagnostic change.

## Risk and P&L

- Preserve fee-aware P&L accounting.
- Do not silently change position sizing, exposure, or risk semantics.
- A risk approval is not proof that an order was executed.
- Distinguish signal approval, risk approval, execution, position commitment, and realized P&L in diagnostics.

## Testing rules

- Run the smallest relevant test set first, then the broader suite when practical.
- Do not claim tests passed unless they actually ran and passed.
- Treat pre-existing failures separately from failures introduced by a change.
- When a test fails, inspect the implementation and test assumptions before weakening or deleting the test.
- Do not merge unrelated fixes into a diagnostic change.

## Change-management rules

- Keep commits focused and reversible.
- Do not merge PR #32.
- PR #39 was previously closed/unmerged and should not be treated as a baseline.
- Do not overwrite working behavior merely to make tests green.
- Prefer small commits with clear messages.
- Before changing an existing file, inspect its current contents and surrounding call graph.

## Required review questions before a strategy change

1. What exact observed problem are we fixing?
2. Which code path produces it?
3. Is the problem reproducible?
4. Could it be caused by market-data freshness, caching, state, risk, execution, or diagnostics rather than strategy logic?
5. What metric will prove improvement?
6. What regression could the change introduce?
7. Has Paper Trading behavior been compared before vs after?

## Definition of done for stabilization

The bot should have a traceable and testable path from market data through entry, risk, execution, position state, exit, and P&L; meaningful Binance traffic should be measurable; known failures should be separated from new regressions; and Paper Trading should be demonstrably safe before strategy optimization is considered complete.
