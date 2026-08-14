# Trade Manager integration conflict register

Target repository: `alihebah649/my-crypto-bot`
Work branch: `tm-integration-work`

This file records integration issues explicitly instead of hiding them inside adapters.

## Resolved in this pass

1. **Repository owner/path mismatch**
   - Correct owner: `alihebah649`.
   - Correct repository: `my-crypto-bot`.
   - Previous `Kamel-Abdullah/shadow-trading-bot` target was incorrect.

2. **Spot-only vs legacy SHORT logic**
   - Part-2 protection models previously exposed `SHORT` and the evaluator contained short-side branches.
   - The active integration contract is spot-only (`LONG` owned-asset position).
   - The protection model/evaluator now reject non-LONG state.

3. **Part-1/Part-8 model boundary**
   - Part-1 runtime bookkeeping was written against the Part-8 `trade_manager.models.Position` contract instead of introducing a second Position class.

4. **Decision vs mutation boundary**
   - Part 3 remains a state-mutation layer over the pure Part-2 evaluator; it does not perform broker calls.

5. **Monitoring isolation**
   - Part 4 monitoring processes positions independently so one position exception does not stop the cycle.

6. **Exit execution boundary**
   - Part 5 exit code requires an injected `ExecutionGateway.close_spot()` rather than silently calling an arbitrary broker API.

7. **Recovery transparency**
   - Part-5 recovery/reconciliation reports missing DB/broker state instead of silently repairing discrepancies.

8. **Core execution ownership**
   - Added `core_execution_gateway.py` as the single adapter from the Trade Manager execution contract to `core.execution_adapter.ExecutionAdapter`.
   - Trade Manager no longer needs a second order implementation for paper/live execution.

9. **Core Position vs Trade Manager Position**
   - Added `core_position_adapter.py` as the explicit conversion boundary.
   - The two models remain separate; callers must convert deliberately instead of duck-typing or duplicating persistence.
   - Negative unrealized P&L is preserved during conversion.

## Still unresolved / must not be guessed

### A. Parts 6 and 7 source contract
The currently available File Library source is `trade manager parts 1-5.docx`; the repository history also shows Part-1 and Part-2 commits. A complete, authoritative Part-6/Part-7 source was not available in the current accessible sources during this pass. Therefore no invented Part-6/Part-7 API is being claimed as final.

### B. Final Paper Trading composition
The core paper adapter exists and can be reached through `CoreExecutionGateway`, but the full application-level composition (strategy -> risk -> execution -> TM position commit -> ledger/reporting) has not yet been proven end-to-end on this branch.

### C. Part-8 facade vs execution gateway
The current Part-8 facade still contains local position lifecycle operations. Before Paper Trading, its close/open responsibilities must be explicitly coordinated with the execution gateway so that a position is not marked closed before a successful execution result is received.

### D. Full Part-5 legacy surface
The original Parts 1-5 document contains several overlapping variants (simple/advanced protection, exit manager/finalizer, recovery manager, monitor thread). The new files preserve responsibilities without copying contradictory variants into one giant module.

## Rule for future integration

Do not delete or silently bypass an item in this register. Any new resolution must be recorded here with the affected contract, the chosen owner of the behavior, and the commit that resolves it.
