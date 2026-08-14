# Trade Manager Integration Conflicts

## Restart / State Continuity — resolved on `tm-state-continuity`

### Conflict
The Trade Manager `PositionRepository` was memory-only. A process restart therefore recreated an empty position set. In Paper Trading this is unsafe because the bot can still own paper assets while Trade Manager has forgotten the corresponding positions.

### Direct fix
- `trade_manager/repository.py` now supports opt-in durable JSON persistence with atomic temp-file replacement.
- `core/paper_execution_adapter.py` now supports opt-in persistence of paper cash/reserved balance/owned assets.
- `trade_manager/shadow_integration.py` wires both stores through `state_dir`.
- `shadow_main.py` supplies `TRADE_MANAGER_STATE_DIR` (default: `data/trade_manager`).
- Restart tests verify both open positions and closed positions, plus the paper cash/asset ledger.

### Deliberate boundary
Persistence is opt-in at the runtime layer so existing isolated unit tests do not share state. The application entry point enables it for Paper Trading.

### Remaining verification
This fix is not considered proven until the repository test suite and the new restart-continuity tests run successfully in CI. No Paper Trading baseline approval is implied by the code change alone.
