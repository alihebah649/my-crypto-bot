# Trade Manager integration conflict register

Target repository: `alihebah649/my-crypto-bot`
Work branch: `tm-integration-work`

This file records integration issues explicitly instead of hiding them inside adapters.

## Resolved

1. **Repository owner/path mismatch** — corrected to `alihebah649/my-crypto-bot`.
2. **Spot-only vs legacy SHORT logic** — active contract is spot-only LONG owned-asset positions.
3. **Part-1/Part-8 model boundary** — canonical Position is `trade_manager.models.Position`.
4. **Decision vs mutation boundary** — protection/risk evaluates; downstream lifecycle mutates state.
5. **Monitoring isolation** — monitoring is isolated from execution and persistence.
6. **Exit execution boundary** — exits route through `ExecutionGateway.close_spot()`; failed execution never closes state.
7. **Recovery transparency** — discrepancies are reported rather than silently hidden.
8. **Core execution ownership** — `core_execution_gateway.py` adapts Trade Manager contracts to `core.execution_adapter.ExecutionAdapter`.
9. **Core Position vs Trade Manager Position** — conversion remains an explicit adapter boundary.
10. **Parts 6/7 source** — `trade manager parts 1-7.docx` is authoritative for those supplied sections; overlapping helpers were normalized.
11. **Part 6/7 -> Part 8** — leverage is fixed at 1.0; typed execution contracts are used; Position state commits only after execution success.
12. **Entry ordering** — typed Part-6 RiskGateway approval precedes BUY; executed quantity/price/commission are authoritative.
13. **REVIEW_REQUIRED** — informational/review state, never automatic SELL.
14. **Paper execution ownership** — existing `PaperExecutionAdapter` remains the execution implementation.
15. **Typed risk boundary** — approved Part-6 quantity is the quantity passed to execution; legacy boolean approval is fallback-only.
16. **Shadow application duplication** — `shadow_main.py` is orchestration-only; lifecycle/risk/execution are delegated to Trade Manager/Core.
17. **Application composition** — `trade_manager/shadow_integration.py` is the explicit composition boundary.
18. **Legacy entrypoint** — `bot.py` is excluded; `shadow_main.py` is canonical.
19. **Paper loss-period accounting** — closed net P&L is rebuilt into Part-6 daily/weekly/monthly periods from each Position's persisted `closed_at` timestamp.
20. **Final lifecycle coverage** — full typed Part-6 -> Core/Part-7 Paper -> Part-8 -> Smart Hold/Recovery -> explicit exit is covered by `tests/test_trade_manager_paper_final_path.py`.
21. **Restart/state continuity** — `PositionRepository` now supports atomic JSON persistence and `PaperExecutionAdapter` persists cash/assets/market prices. `ShadowTradeManagerRuntime` wires both through one `persistence_dir`.
22. **Restart regression gate** — `tests/test_paper_restart_continuity.py` proves an open position and paper account survive construction of a second runtime using the same state directory.
23. **Paper application persistence** — `shadow_main.py` now supplies `PAPER_STATE_DIR` (default `data/paper`) to the runtime.
24. **Score-path gap** — the deployed application was scoring only EMA100/RSI, so a coin above EMA100 with neutral RSI could plateau at 50 and never reach the intended BUY threshold. The strategy path now restores 15m Bollinger support, EMA100 trend, RSI zones, 15m volume confirmation, and 5m bullish candle confirmation into one bounded 0-100 score.
25. **Strategy timeframe gap** — the previous shadow runtime built indicators from a one-minute live tick resampler and required 101 closed candles before scoring. The paper strategy now consumes Binance Spot 15m/5m historical candles directly, so the strategy is available immediately after startup instead of waiting for more than 100 minutes of local history.
26. **Universe gap** — `shadow_main.py` previously subscribed to only 7 Coinbase USD products while the established strategy universe contained 16 Binance Spot USDT pairs. The paper runtime now evaluates the full 16-symbol Binance Spot universe: BTC, ETH, SOL, LINK, ADA, DOT, NEAR, ARB, OP, RENDER, BNB, AVAX, ALGO, ATOM, FET and LTC.
27. **Prospective exposure gap** — Part-6 previously checked only current portfolio exposure before sizing. The risk gateway now rejects a new position when current exposure plus the proposed position would exceed the configured portfolio exposure cap.
28. **Score regression gate** — `tests/test_shadow_score_strategy.py` verifies the 16-symbol universe and verifies that BUY can be reached from the combined strategy conditions rather than an EMA-only shortcut.

## Remaining validation work / blockers

### A. GitHub Actions final validation
The branch must have a successful GitHub Actions run after the latest strategy/risk changes before the Paper Trading baseline can be declared green.

### B. Exchange-specific execution details
Part-7 broker-specific REST skeletons remain non-authoritative. Concrete exchange execution stays in `core.execution_adapter` and its adapters.

### C. Exchange filter provider
Part 6 contains `PositionSizeNormalizer`, but the Paper composition intentionally has no exchange lot-filter provider. Before live Binance execution, the real exchange-info provider must be wired into the Part-6 gateway.

### D. Strategy data availability
The paper strategy now uses Binance public REST market data for 15m/5m candles and 24h ticker data. A prolonged Binance public API outage must be treated as a data-unavailable condition; it must not create synthetic BUY signals.

### E. Recovery reconciliation after process crash
Persistence now restores local Position/account state. A live exchange reconciliation source is still required before live trading so the persisted state can be compared against actual broker holdings after an unexpected crash.

## Rule for future integration

Do not delete or silently bypass an item in this register. Any new resolution must be recorded here with the affected contract, chosen owner of the behavior, and resolving commit.
