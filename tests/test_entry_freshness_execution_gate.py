from core.entry_freshness_audit import entry_execution_freshness_allowed


def test_fresh_and_recent_data_allow_scalp():
    assert entry_execution_freshness_allowed({"state": "FRESH"}, "SCALP") is True
    assert entry_execution_freshness_allowed({"state": "RECENT"}, "SCALP") is True


def test_stale_data_blocks_only_scalp():
    assert entry_execution_freshness_allowed({"state": "STALE"}, "SCALP") is False
    assert entry_execution_freshness_allowed({"state": "STALE"}, "SWING") is True


def test_missing_or_unknown_freshness_preserves_existing_behavior():
    assert entry_execution_freshness_allowed(None, "SCALP") is True
    assert entry_execution_freshness_allowed({"state": "UNKNOWN"}, "SCALP") is True
