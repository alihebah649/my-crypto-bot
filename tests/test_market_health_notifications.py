from core.market_health_notifications import should_notify_market_health


def test_main_bot_keeps_hourly_market_health_heartbeat():
    assert should_notify_market_health(
        venue_mode="MIXED", changed=False, heartbeat_due=True
    ) is True


def test_bybit_lab_suppresses_unchanged_hourly_market_health_heartbeat():
    assert should_notify_market_health(
        venue_mode="BYBIT_ONLY_LAB", changed=False, heartbeat_due=True
    ) is False


def test_okx_lab_suppresses_unchanged_hourly_market_health_heartbeat():
    assert should_notify_market_health(
        venue_mode="OKX_ONLY_LAB", changed=False, heartbeat_due=True
    ) is False


def test_lab_still_reports_market_health_state_transitions():
    for venue in ("BYBIT_ONLY_LAB", "OKX_ONLY_LAB"):
        assert should_notify_market_health(
            venue_mode=venue, changed=True, heartbeat_due=False
        ) is True


def test_forced_market_health_notification_is_preserved():
    assert should_notify_market_health(
        venue_mode="OKX_ONLY_LAB", changed=False, heartbeat_due=False, force=True
    ) is True
