# Paper Trading Integration Contract

## Canonical runtime path

`shadow_main.py`
→ `pipeline.paper_trading_runner.PaperTradingRunner`
→ public Binance market data
→ `core.indicators_engine.IndicatorEngine`
→ `core.risk_engine.RiskEngine`
→ `core.execution_models.ExecutionRequest`
→ `core.execution_engine.ExecutionEngine`
→ `core.paper_execution_adapter.PaperExecutionAdapter`
→ `core.portfolio_engine.PortfolioEngine`
→ `core.recovery_engine.RecoveryEngine`

The execution source for this path is **PAPER only**. No live Binance order adapter is used by the canonical entry point.

## Accounting contract

- `PaperExecutionAdapter` is the execution simulator.
- `PortfolioEngine` is the canonical portfolio/accounting state.
- A successful paper BUY/SELL must be reflected in both layers.
- The runner raises a hard error if execution succeeds but portfolio state cannot be updated.
- The integration tests assert that paper-adapter cash and portfolio free balance remain equal after a complete round trip.

## Risk contract

- Entry sizing is delegated to the existing `RiskEngine`.
- The runner does not bypass a rejected risk decision.
- Minimum notional comes from the existing configuration.
- Open-position and portfolio-exposure limits remain enforced by `RiskEngine`.

## Exit / recovery contract

- Profitable SELL signals may close a position.
- A losing position is not automatically sold merely because a SELL signal appears.
- Losing positions enter the existing `RecoveryEngine` path when recovery is enabled.
- Recovery may hold, complete, or explicitly request a SELL according to its existing rules.
- Existing stop, break-even, and trailing protections remain active.

## Conflicts found and resolved

1. **Legacy `shadow_main.py` was a monolithic Coinbase-based simulator.**
   - It bypassed the current `core/*` architecture and did not use the canonical execution/risk/portfolio contracts.
   - **Resolution:** replaced it with a thin canonical entry point that starts the paper integration runner.

2. **Two incompatible execution contracts existed.**
   - The historical Trade Manager part 7 skeleton defines its own order/response objects, while the current repository already has `core.execution_models` and `ExecutionAdapter`.
   - **Resolution:** the current runtime uses `core.execution_models` + `ExecutionAdapter` as the executable contract. The old skeleton remains reference material and is not invoked by the paper path.

3. **Two balance authorities existed.**
   - The paper adapter maintains simulated exchange cash/assets while `PortfolioEngine` maintains accounting state.
   - **Resolution:** adapter = execution simulation; PortfolioEngine = accounting authority; parity is checked after successful fills.

4. **Losing SELL signals conflicted with Smart Hold / Recovery.**
   - The old entry point sold directly on SELL signals.
   - **Resolution:** the paper path only closes a profitable position on a normal SELL signal; losing positions are routed through RecoveryEngine when recovery is enabled.

5. **Obsolete `bot.py` competed with the canonical entry point.**
   - **Resolution:** removed `bot.py`; `shadow_main.py` is now the only canonical application entry point.

6. **`core/models.py.` was a duplicate/backup-looking source file.**
   - The canonical runtime imports `core.models`, while the dotted backup file is not a Python module path used by those imports.
   - **Resolution:** it is treated as non-runtime legacy material and should not be used as a source of truth.
