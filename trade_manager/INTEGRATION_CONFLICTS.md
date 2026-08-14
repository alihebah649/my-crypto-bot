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
   - Part-2 protection models previously exposed SHORT behavior.
   - The active integration contract is spot-only (`LONG` owned-asset position).
   - Protection models/evaluator reject non-LONG state.

3. **Part-1/Part-8 model boundary**
   - Part-1 runtime bookkeeping uses the canonical Part-8 `trade_manager.models.Position` contract.
   - No second Position persistence model was introduced.

4. **Decision vs mutation boundary**
   - Part 2 evaluates protection decisions; Part 3 applies state mutations.
   - Part 3 does not place broker/network orders.

5. **Monitoring isolation**
   - Part 4 processes positions independently so one position exception does not stop the cycle.

6. **Exit execution boundary**
   - Part 5/8 exit flow is routed through `ExecutionGateway.close_spot()`.
   - The controller refuses to mark a position CLOSED when execution is missing, rejected or failed.
   - The actual exit price and commission come from the execution result when available.

7. **Recovery transparency**
   - Part-5 recovery/reconciliation reports missing DB/broker state instead of silently repairing discrepancies.

8. **Core execution ownership**
   - `core_execution_gateway.py` remains the single adapter from Trade Manager execution contracts to `core.execution_adapter.ExecutionAdapter`.
   - Trade Manager does not duplicate Binance/paper order implementation.

9. **Core Position vs Trade Manager Position**
   - `core_position_adapter.py` remains the explicit conversion boundary.
   - Negative unrealized P&L is preserved during conversion.

10. **Parts 6 and 7 authoritative source availability**
   - The complete `trade manager parts 1-7.docx` is now available and was used as the source for `part6_risk.py` and `part7_execution.py`.
   - The overlapping source helpers were normalized into separate files rather than copied into one conflicting module.
   - Part 6 owns pre-entry risk/sizing/limits/locks and never executes orders.
   - Part 7 owns execution contracts/building/error handling/pipeline and never mutates Position state.

11. **Part 6/7 -> Part 8 contract**
   - Part 6 uses spot-only sizing with leverage fixed to 1.0.
   - Part 7 maps to the canonical `integration_contracts.ExecutionGateway`.
   - Part 8 Position state is committed only after a successful execution result.

12. **Entry ordering**
   - `PositionManagementFacade.open_position()` now requires an injected execution gateway and explicit Part-6 risk approval callback before sending BUY.
   - A failed/rejected execution creates no Position record.
   - Executed quantity/price/commission become the Position's authoritative entry values.

13. **Review-required semantics**
   - `REVIEW_REQUIRED` is a state requiring explicit human/system review and is not treated as an automatic sell.

14. **Trade Manager -> core Paper Execution lifecycle**
   - Added integration coverage proving BUY execution through `CoreExecutionGateway`, Position creation in the Trade Manager facade, successful SELL/close through the same gateway, fee/P&L propagation, and preservation of an OPEN Position when the exit execution fails.
   - GitHub Actions run `31766297912` passed the new end-to-end Trade Manager paper contract tests.

15. **CI coverage gap for Trade Manager integration**
   - The workflow previously ran only the isolated paper execution test and one integration smoke test.
   - It now runs the Part 6/7 contract tests, Trade Manager integration tests, and the Trade Manager -> core Paper Execution end-to-end tests on every push to `tm-integration-work`.
   - GitHub Actions run `31766326362` passed all four test stages before the latest Part-6 composition additions.

16. **Application-level strategy -> Trade Manager boundary**
   - `core/trade_manager_composition.py` is now the explicit application composition boundary.
   - It accepts a normalized `EntrySignal`, obtains account inputs through an injected provider, requests authoritative Part-6 sizing/approval, and only then calls the Part-8 facade.
   - It does not implement strategy logic, risk math, broker calls, or Position mutation.
   - The facade remains the final execution gate and Position owner.

17. **Part-6 core-state hand-off**
   - `trade_manager/core_risk_gateway.py` now adapts the existing Part-6 `RiskController` and `PositionSizeCalculator` to the application `RiskGateway` contract.
   - `trade_manager/core_risk_providers.py` converts the existing core portfolio snapshot into the exact Part-6 portfolio contract and defines an explicit market-data provider boundary.
   - No duplicate account or market state is created.
   - The gateway fails closed on missing/invalid data and enforces spot leverage of 1.0.
   - A dedicated CI test now verifies Part-6 approval -> Trade Manager -> core Paper Execution.

## Remaining validation work (not a code contradiction)

### A. Full application-level Paper Trading composition
The explicit composition and Part-6 provider boundaries now exist. The remaining end-to-end validation is wiring the **actual strategy/signal producer** and **actual live/paper market-data provider** into these boundaries, then testing:

`strategy/signal -> Part-6 risk -> Trade Manager entry -> core execution -> Position/ledger synchronization -> reporting`.

This must be verified before treating the branch as the final Paper Trading baseline.

### B. Exchange-specific execution details
The Part-7 document contains broker-specific skeletons. Concrete Binance/REST details remain owned by `core.execution_adapter`; they must not be reimplemented in Trade Manager.

### C. Legacy Part-5 variants
The original Parts 1-5 document contains overlapping simple/advanced protection, exit, recovery and monitor variants. The repository keeps one canonical implementation per responsibility and records the source variants here rather than duplicating them.

### D. Legacy runtime migration
`bot.py` still contains the legacy V2 runtime with embedded strategy, market-data acquisition, position state and execution bookkeeping. The current `engine/*.py` entry/exit/market files are placeholders. Therefore the real strategy producer is **not yet a reusable provider** for `TradeManagerApplicationCoordinator`.

`bot.py` must not be silently rewritten merely to make the new composition appear connected. Its migration requires an explicit extraction/adaptation step followed by integration tests.

## Rule for future integration

Do not delete or silently bypass an item in this register. Any new resolution must be recorded here with the affected contract, the chosen owner of the behavior, and the commit that resolves it.
