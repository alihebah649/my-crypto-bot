# Stale ticker entry guard

Paper Trading must not open a new position when market-data continuity depends on a stale 24h ticker snapshot. Stale ticker data remains diagnostic-only until a fresh ticker response clears the guard.

SCALP/SWING thresholds and strategy rules are unchanged.