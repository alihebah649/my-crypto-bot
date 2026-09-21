from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy


def test_current_allows_new_entries_and_existing_position_management():
    policy = SettlementTradingPolicy(SettlementState.CURRENT)
    assert policy.allow_new_entries is True
    assert policy.manage_existing_positions is True
    assert policy.force_close_existing_positions is False


def test_settlement_required_blocks_new_entries_but_never_closes_existing():
    policy = SettlementTradingPolicy(SettlementState.SETTLEMENT_REQUIRED)
    assert policy.allow_new_entries is False
    assert policy.manage_existing_positions is True
    assert policy.force_close_existing_positions is False


def test_disabled_has_same_position_safety_boundary():
    policy = SettlementTradingPolicy(SettlementState.DISABLED)
    assert policy.allow_new_entries is False
    assert policy.manage_existing_positions is True
    assert policy.force_close_existing_positions is False
