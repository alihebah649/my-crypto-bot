# Trade Manager Integration Contract

## Status

Baseline integration pass completed on `main`.

## Canonical ownership

- **Part 6 (`trade_manager.risk`)**: pre-entry risk gate, sizing, exposure, market filters, loss limits and risk lock.
- **Part 7 (`trade_manager.execution`)**: broker-neutral order contract and execution pipeline. It must not contain strategy or portfolio accounting decisions.
- **Part 8.1-8.8 (`trade_manager`)**: canonical open-position lifecycle, Smart Hold/Recovery, P&L/fees, synchronization, metrics and history.
- **`core.models.Position` / `core.portfolio_engine.PortfolioEngine`**: core portfolio/accounting authority. Trade Manager must not silently replace this accounting state.
- **`trade_manager.core_bridge`**: the only translation boundary between the core position representation and the Trade Manager Part-8 representation.

## Conflicts found and fixed

1. **Part-8 `Position` was referenced but absent from the live `trade_manager/models.py`.**
   - Fixed by restoring the Part-8 canonical `Position`, `PositionStatus`, `PositionSide` and `PositionCloseReason` models while preserving the Parts 1-7 compatibility models.

2. **Parts 1-7 and Part 8 had two different position models with no explicit boundary.**
   - Fixed by documenting Part 8 as canonical for lifecycle state and retaining `ManagedPosition` only as a compatibility boundary.

3. **Part-1-to-7 manager attempted to assign `last_update` to a slotted model that did not define the field.**
   - Fixed by making `last_update` an explicit field and updating it safely.

4. **Part-8 manual close was encoded as `REVIEW_REQUIRED`.**
   - Fixed with an explicit `MANUAL` exit reason and controller mapping.

5. **Part-8 exit risk and Part-6 entry risk were conflated conceptually.**
   - Fixed by keeping `RiskManager` (entry gate) separate from `PositionRiskManager` (open-position exit/recovery manager).

6. **Part-6 loss limits were declared in the original design but absent from the live risk implementation.**
   - Fixed by adding `LossTracker`, daily/weekly/monthly risk managers and `RiskLockManager`.

7. **Core and Trade Manager each define a `Position` model.**
   - Fixed by adding an explicit `core_bridge` translation layer rather than importing one model into the other.

8. **Paper execution already has its own core execution contract.**
   - No direct Binance client was added to Trade Manager. Part 7 remains broker-neutral; the next integration step is an explicit adapter between `core.execution_adapter.ExecutionAdapter` and `trade_manager.execution.ExecutionBroker`.

## Remaining integration work

- Wire `shadow_main.py` to the canonical core engines and this Trade Manager facade.
- Add the explicit Core Execution Adapter -> Part-7 Broker adapter.
- Run the new Trade Manager contract tests in GitHub Actions and resolve any environment-specific failures.
- Only after those checks pass should the system be treated as the Paper Trading baseline.

## Safety rule

No live Binance order path is considered approved merely because the Trade Manager unit tests pass. Paper execution, portfolio accounting, synchronization and the main runtime must all pass the integration contract first.
