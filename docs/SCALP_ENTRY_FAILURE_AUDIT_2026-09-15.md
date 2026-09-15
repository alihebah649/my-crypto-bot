# SCALP Entry Failure Audit — 2026-09-15

## Purpose

Diagnostic-only record. This document does **not** change trading logic, thresholds, risk limits, or exit behavior.

## Current decision

- Keep `SCALP_SCORE_THRESHOLD = 65`.
- Do not treat EMA100 as a sufficient explanation for losses.
- Do not change the production `main` branch.
- Do not change exit/Trade Manager behavior from this audit alone.
- Continue collecting outcome-linked entry records before promoting a new entry rule.

## Evidence from diagnostics

| Symbol | Entry score | Trigger | MTF net | Recovery | Notes |
|---|---:|---|---:|---|---|
| TRXUSDT | 77 | confirmed 5m bullish breakout | +9 | yes, 3/3 | Price was close to EMA100; strong 5m volume; multi-timeframe context was supportive enough to avoid a countertrend veto. |
| FETUSDT | 85 (snapshot later also records 66 for the same entry trace) | confirmed 5m bullish breakout | +4 | yes, 3/3 | Entry price 0.1637; EMA100 at the captured entry context was above price in the earlier loss record. The later diagnostic context shows bearish drift developing after entry. |
| ADAUSDT | 81 | confirmed 5m bullish engulfing | -1 | yes, 3/3 | Higher-timeframe picture was essentially mixed/neutral; entry was below EMA100. |
| BNBUSDT | 87 (entry trace also records 65 in a later diagnostic snapshot) | confirmed 5m bullish engulfing | -1 | yes, 3/3 | Entry was below EMA100 and MTF was slightly bearish overall. |
| BTCUSDT | 66 | recovery-only (no confirmed bullish pattern) | -20 | yes, 3/3 | Strongest countertrend example: gate could pass through recovery even with strongly negative MTF because the hard veto only applies when the recovery is not classified as a confirmed reversal. |
| SUIUSDT | 75 | recovery-only / bullish engulfing unconfirmed | -14 | yes, 3/3 | Recovery triggers supplied the gate while MTF remained materially bearish. |
| LTCUSDT | 70 | recovery-only / no confirmed pattern | -26 | yes, 3/3 | Strong negative MTF with no confirmed bullish pattern; this is a high-priority candidate for outcome validation. |
| ETHUSDT | 71 | confirmed 5m bullish breakout | +15 | yes, 3/3 | MTF supportive; entry below EMA100 in the captured context. |
| BCHUSDT | 69 | confirmed 5m hammer | +4 | yes, 3/3 | Mixed MTF: 1h bearish but 4h bullish; gate passed through confirmed reversal. |
| AVAXUSDT | 93 | confirmed 5m morning star | +4 | yes, 3/3 | High score and confirmed reversal; MTF slightly positive despite mixed frame structure. |

## Failure-mode assessment

The strongest currently observable risk is **countertrend recovery contamination**: the scalp gate allows a recovery-only setup to enter while higher-timeframe structure is materially bearish. The diagnostics explicitly show recovery as three triggers (`5M_RSI_RISING`, `5M_PRICE_RECOVERY`, `5M_BULLISH_BODY`) and a separate confirmed-pattern path. Recovery can therefore satisfy the gate without a confirmed bullish pattern.

This is a candidate failure mode, not yet a proven causal rule. The present sample is too small and contains mixed outcomes, so a production restriction such as `MTF <= X => reject` should not be promoted from this document alone.

## Next measurement

For every newly opened SCALP position, preserve and later join:

1. position ID
2. exact entry timestamp
3. captured entry context
4. entry score and trigger type
5. EMA100 distance at entry
6. MTF net / weighted bull / weighted bear
7. recovery trigger count
8. confirmed-pattern flag/name
9. stop distance
10. final close reason and realized P&L
11. maximum favorable excursion and maximum adverse excursion

The key comparison is **outcome by trigger class**:

- confirmed reversal + supportive MTF
- confirmed reversal + neutral/mixed MTF
- confirmed reversal + bearish MTF
- recovery-only + supportive MTF
- recovery-only + bearish MTF

Only after enough outcome-linked observations should an entry-rule change be considered.

## Separate operational finding

The diagnostics also show a hard `MAX_OPEN_SCALP_POSITIONS` rejection when 15 scalp positions were already open. This is an independent capacity issue and should not be conflated with signal quality.
