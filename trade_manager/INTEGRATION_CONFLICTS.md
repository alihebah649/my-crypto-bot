# Trade Manager integration conflict register

Target repository: `alihebah649/my-crypto-bot`
Work branch: `tm-integration-work`

This file records integration issues explicitly instead of hiding them inside adapters.

## Resolved

1. **Repository owner/path mismatch**
   - Correct owner: `alihebah649`.
   - Correct repository: `my-crypto-bot`.
   - Previous `Kamel-Abdullah/shadow-trading-bot` target was incorrect.

2. **Spot-only vs legacy SHORT logic**
   - The active integration contract is spot-only (`LONG` owned-asset position).

3. **Part-1/Part-8 model boundary**
   - The canonical Position contract is `trade_manager.models.Position`.

4. **Decision vs mutation boundary**
   - Protection evaluates decisions; state mutation remains downstream.

5. **Monitoring isolation**
   - Monitoring is isolated from execution and persistence.

6. **Exit execution boundary**
   - Exit flow is routed through `ExecutionGateway.close_spot()`.
   - Failed execution never marks a Position CLOSED.

7. **Recovery transparency**
   - Recovery/reconciliation reports discrepancies rather than silently hiding them.

8. **Core execution ownership**
   - `core_execution_gateway.py` is the adapter from Trade Manager execution contracts to `core.execution_adapter.ExecutionAdapter`.

9. **Core Position vs Trade Manager Position**
   - `core_position_adapter.py` remains the explicit conversion boundary.

10. **Parts 6 and 7 authoritative source availability**
   - `trade manager parts 1-7.docx` is the source used for Parts 6 and 7.
   - Overlapping helpers were normalized into separate modules.
   - Part 6 owns pre-entry risk/sizing/limits/locks and never executes orders.
   - Part 7 owns execution contracts/building/error handling/pipeline and never mutates Position state.

11. **Part 6/7 -> Part 8 contract**
   - Spot leverage is fixed at 1.0.
   - Part 7 maps to `integration_contracts.ExecutionGateway`.
   - Part 8 commits Position state only after successful execution.

12. **Entry ordering**
   - `PositionManagementFacade.open_position()` now prefers the typed `RiskGateway` contract.
   - BUY is submitted only after Part-6 approval.
   - Executed quantity/price/commission are authoritative.

13. **Review-required semantics**
   - `REVIEW_REQUIRED` is not an automatic sell.

14. **Trade Manager -> core Paper Execution lifecycle**
   - The existing paper execution adapter remains the execution implementation; Trade Manager only adapts to it.

15. **Typed Part-6 risk boundary**
   - `PositionManagementFacade` accepts `RiskGateway` and sends a `RiskSizingRequest` before entry.
   - The approved quantity returned by Part 6 is the quantity passed to execution.
   - Legacy boolean approval is retained only as a compatibility fallback and does not perform sizing.

16. **Shadow application had a second Portfolio/Risk/Execution stack**
   - The previous `shadow_main.py` contained its own `GlobalPortfolioTracker`, `DynamicRiskEngine`, stop/trailing logic, and direct BUY/SELL bookkeeping.
   - This duplicated Trade Manager Parts 6-8 and would have created divergent state.
   - `shadow_main.py` was replaced with an orchestration-only entry point.
   - Market data and strategy signals remain in the application layer; lifecycle/risk/execution now flow through `ShadowTradeManagerRuntime`.

17. **Application composition boundary**
   - Added `trade_manager/shadow_integration.py` as the explicit composition boundary for Shadow Trading.
   - It wires the Part-6 `RiskController`/sizer, Part-7 `CoreExecutionGateway`, and Part-8 repository/controller/facade.
   - It provides a single market-state provider used by both entry risk and position management.
   - It uses the existing `PaperExecutionAdapter` rather than implementing another paper portfolio.

18. **Legacy entrypoint removal**
   - `bot.py` was deleted from `tm-integration-work` because `shadow_main.py` is now the canonical application entry point.
   - No Trade Manager logic depends on `bot.py`.

19. **Paper loss-period accounting**
   - Resolved for the Shadow/Paper composition by adding `_PaperLossPeriodLedger` in `trade_manager/shadow_integration.py`.
   - Closed Position `realized_pnl` is now fed into Part-6 daily/weekly/monthly `LossTracker` snapshots exactly once per position.
   - A regression test verifies that a loss crossing the configured daily limit rejects the next risk approval.

## Remaining validation work (not a hidden contradiction)

### A. Full application-level Paper Trading validation
The application-level composition now exists and has focused contract coverage for:

`strategy signal -> Part-6 risk -> Trade Manager entry -> core paper execution -> Position management -> Smart Hold -> REVIEW_REQUIRED -> explicit exit -> fee-aware P&L -> Part-6 loss feedback`.

The full GitHub regression suite still needs to execute successfully before calling the branch the final Paper Trading baseline.

### B. Exchange-specific execution details
Part-7 broker-specific REST skeletons remain non-authoritative. Concrete exchange execution stays in `core.execution_adapter` and its adapters.

### C. Exchange filter provider
Part 6 contains `PositionSizeNormalizer`, but the paper composition intentionally has no exchange lot-filter provider. Before live Binance execution, the real exchange-info provider must be wired into the Part-6 gateway.

### D. Strategy signal ownership
`shadow_main.py` still owns the existing EMA/RSI signal calculation because that code is application/strategy logic, not Trade Manager logic. It must not directly mutate positions or execute orders.

## Rule for future integration

Do not delete or silently bypass an item in this register. Any new resolution must be recorded here with the affected contract, chosen owner of the behavior, and resolving commit.
