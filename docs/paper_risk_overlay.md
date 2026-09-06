# Paper Risk Overlay

This Paper-only orchestration overlay addresses five observed operational problems without changing Strategy thresholds or Trade Manager code.

- SCALP remains 65; SWING remains 80.
- Loss cooldown is symbol-wide for 2 hours after a realized losing exit.
- Profitable retracements can be protected before TP once profit has reached 0.35% and retraced at least 0.20%.
- BTC may enter bounded Recovery instead of its initial stop when its individual setup remains strong and BTC is not in crash mode; the Paper-only emergency floor is 1.20% below entry.
- During BTC crash mode, normal entries remain blocked. A narrow exception permits only a Swing setup at 90+ with EMA100 trend, confirmed bullish pattern, and higher-timeframe bullish alignment.
- Paper STOP_LOSS fills are modeled at the configured stop when the polling loop detects a breach, so polling latency is not counted as artificial strategy slippage.

The overlay is deliberately outside Trade Manager and is intended for Paper Trading validation first.