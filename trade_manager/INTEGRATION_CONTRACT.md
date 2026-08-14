# Trade Manager Integration Contract

## Status

Integration is being stabilized on `main`. Part 7 now has an explicit adapter boundary into the existing core execution layer.

## Canonical ownership

- **Part 6 (`trade_manager.risk`)**: pre-entry risk gate, sizing, exposure, market filters, loss limits and risk lock.
- **Part 7 (`trade_manager.execution`)**: broker-neutral order contract and execution pipeline. It must not contain strategy or portfolio accounting decisions.
- **`trade_manager.core_execution_adapter`**: the only translation boundary from the Part-7 broker contract to `core.execution_adapter.ExecutionAdapter`.
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
   - Fixed the missing integration boundary by adding `CoreExecutionBrokerAdapter`. Part 7 remains broker-neutral and delegates execution-model translation to this adapter.

## Current integration sequence

```text
Signal / Strategy
       |
       v
Part 6 Risk Gate
       |
       v
Trade Manager Facade / Part 8 Lifecycle
       |
       v
Part 7 ExecutionPipeline
       |
       v
CoreExecutionBrokerAdapter
       |
       v
core.execution_adapter.ExecutionAdapter
       |
       +---- PaperExecutionAdapter (Paper)
       +---- BinanceExecutionAdapter (Live, not approved here)
```

Portfolio accounting remains a separate authority:

```text
Executed fill -> core PortfolioEngine -> core.models.Position
                              ^
                              |
                   trade_manager.core_bridge
                              |
                    Trade Manager Position
```

The bridge is deliberately explicit so the two `Position` models cannot silently replace each other.

## Remaining integration work

- Wire the root `shadow_main.py` to the canonical core engines and Trade Manager facade using the boundaries above.
- Keep `bot.py` out of the runtime path; it is legacy and is not part of the new entry-point contract.
- Verify the full runtime path with paper execution, portfolio accounting, synchronization and the main runtime.
- Run the GitHub Actions contract tests and resolve environment-specific failures before declaring the Paper Trading baseline ready.

## Safety rule

No live Binance order path is considered approved merely because the Trade Manager unit tests pass. Paper execution, portfolio accounting, synchronization and the main runtime must all pass the integration contract first.
