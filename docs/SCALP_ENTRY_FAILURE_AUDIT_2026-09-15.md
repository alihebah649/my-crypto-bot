# SCALP Entry Failure Audit — 2026-09-15

## Purpose

Diagnostic-only record. This document does **not** change trading logic, thresholds, risk limits, or exit behavior.

## Current decision

- Keep `SCALP_SCORE_THRESHOLD = 65`.
- Do not treat EMA100 alone as the explanation for losses.
- Do not change the production `main` branch.
- Do not change exit/Trade Manager behavior from this audit alone.
- Do not promote a new entry rule until entry context is reliably joined to the final position outcome.

## What the current evidence actually shows

The captured sample contains both confirmed 5m reversals and recovery-only entries. Several losing SCALP trades were **confirmed-pattern entries**, so "recovery contamination" is real but is not the whole problem.

The more useful common pattern is **weak structural context at the moment of entry**:

1. price is below EMA100, and/or
2. MTF net is weak/negative,
3. while the 5m trigger still supplies enough points/gate conditions to buy.

This is a better candidate failure mode than score threshold alone because it explains why scores in the 65–90 range can still produce poor entries.

## Known closed losses and entry context

The user-provided closed-loss log contains 8 losses: 7 SCALP and 1 SWING.

| Position/Case | Mode | Entry score | Trigger | Entry vs EMA100 | MTF net | Outcome |
|---|---|---:|---|---:|---:|---|
| TRXUSDT | SCALP | 77 | confirmed bullish breakout | +0.14% | +9 | loss |
| FETUSDT | SCALP | 79 in loss log; diagnostics also contain 85/66 trace snapshots | confirmed bullish breakout | about -2.87% | +4 | loss |
| ADAUSDT | SCALP | 66 in loss log; captured context 81 | confirmed bullish engulfing | about -0.50% | -1 | loss |
| BTCUSDT | SCALP | 75 in loss log; captured context 66 | recovery-only | about -0.05% | -20 | loss |
| BNBUSDT | SCALP | 75 in loss log; captured context 87 | confirmed bullish engulfing | about -0.44% | -1 | loss |
| DOTUSDT | SCALP | 65 | entry context not reliably matched in the uploaded snapshot | below EMA100 in the loss log | not safely attributable | loss |
| SOLUSDT | SCALP | 65 | confirmed bullish breakout | about +1.09% | +23 | loss |
| BTCUSDT | SWING | 80 | swing lane | about +0.08% | not treated as SCALP evidence | loss |

The uploaded diagnostics directly confirm the detailed entry contexts for TRX, FET, ADA, BTC, BNB and SOL. For example, TRX entered at 0.3407 with EMA100 0.3402235 and MTF +9, while BTC SCALP entered at 78150.41 with EMA100 78186.24 and MTF -20. ADA entered at 0.2085 with EMA100 0.2095546 and MTF -1. FET entered at 0.1637 with EMA100 0.1685318 and MTF +4. fileciteturn160file2 fileciteturn160file14 fileciteturn160file0 fileciteturn161file15

## Immediate finding

Among the **7 known SCALP losses**, 5 entered below EMA100 and 2 entered above EMA100. This is meaningful as a screening clue, but it is not enough to prove causality because we do not yet have a comparable set of closed winning SCALPs with the same fields.

The MTF signal is even more revealing about the failure modes:

- BTC SCALP is the clearest recovery-only countertrend case: MTF net -20 and no confirmed 5m bullish pattern, yet the recovery gate passed. fileciteturn160file14
- ADA and BNB show that a confirmed 5m pattern can still enter with slightly negative MTF (-1) and below-EMA price. fileciteturn160file0 fileciteturn161file18
- FET shows that even a confirmed breakout and slightly positive MTF (+4) can still fail when price is materially below EMA100. fileciteturn161file15
- SOL demonstrates the opposite side of the hypothesis: price was above EMA100 and MTF was strongly positive (+23), yet the trade still lost. Therefore the proposed structural filter cannot be treated as a guaranteed win condition. fileciteturn160file4

## Candidate rule — NOT production

A **candidate** worth testing offline is:

> When a SCALP setup is below EMA100, require materially supportive MTF context before allowing the entry; do not let recovery or a weak 5m reversal alone override clearly weak structure.

A concrete first test boundary is **MTF net >= +5 for below-EMA SCALPs**. This boundary is intentionally a test hypothesis, not an implementation decision.

Why +5 is a useful first experiment:

- it would have screened the observed FET (+4), ADA (-1), BNB (-1), and BTC (-20) cases;
- it would still allow a below-EMA setup with stronger MTF, such as the captured ETH case at +15; and
- it does not raise the SCALP score threshold above 65.

However, this experiment can only be accepted after measuring how many profitable historical/current SCALPs it would also reject.

## Recovery-only sub-test

A second, stricter experimental hypothesis is:

> Recovery-only entries should require stronger structural confirmation than confirmed-pattern entries.

The current diagnostics contain recovery-only examples at MTF -20 (BTC), -14 (SUI), and -26 (LTC), showing exactly why this deserves a separate test bucket. fileciteturn161file19 fileciteturn161file6

## What must be measured next

For each real SCALP position, join the same `position_id` across the entire lifecycle and record:

- exact entry timestamp and filled entry price;
- entry score;
- trigger class: confirmed reversal / recovery-only;
- EMA100 distance at entry;
- MTF net, weighted bull, weighted bear;
- recovery trigger count;
- 5m volume ratio;
- RSI15m and RSI5m;
- stop distance;
- final close reason and realized P&L;
- MAE/MFE when available.

The decisive comparison is not "did the score exceed 65?" but **which structural/trigger combination has positive expectancy**.

## Operational issue kept separate

When 15 SCALP positions were already open, Part 6 rejected a later SCALP with `MAX_OPEN_SCALP_POSITIONS`. This is a capacity/concentration issue and must not be mixed into signal-quality analysis. fileciteturn159file15

## Status

**No production trading rule changed.**

The next implementation step should be an **offline/replay test of the candidate structural filter**, using the current `dual_mode_strategy` rather than the old independent replay strategy. Only a statistically useful outcome sample should decide whether the candidate belongs in the real entry gate.