from datetime import datetime, timezone

from trade_manager.risk_periods import period_keys, same_period


def test_daily_period_uses_asia_aden_midnight():
    # 2026-08-23 21:30 UTC is already 2026-08-24 00:30 in Asia/Aden.
    before = datetime(2026, 8, 23, 21, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 23, 22, 1, tzinfo=timezone.utc)
    assert period_keys(before)[0] == "2026-08-24"
    assert period_keys(after)[0] == "2026-08-24"


def test_daily_boundary_changes_at_aden_midnight():
    before = datetime(2026, 8, 23, 21, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 23, 22, 1, tzinfo=timezone.utc)
    assert same_period(before, after)


def test_previous_aden_day_is_distinct():
    previous = datetime(2026, 8, 23, 21, 59, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 24, 22, 1, tzinfo=timezone.utc)
    assert period_keys(previous)[0] == "2026-08-24"
    assert period_keys(next_day)[0] == "2026-08-25"
    assert not same_period(previous, next_day)
