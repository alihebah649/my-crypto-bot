from core.binance_reconciliation import (
    AccountLocalPositionView,
    ExchangeAsset,
    LocalPositionView,
    reconcile_account_spot_positions,
    reconcile_spot_positions,
)


def test_exchange_position_without_local_record_blocks_resume():
    result = reconcile_spot_positions(
        [ExchangeAsset("ADAUSDT", 10.0)],
        [],
        {},
    )
    assert result.safe_to_resume is False
    assert result.has_orphans is True
    assert result.issues[0].code == "ORPHAN_POSITION"


def test_local_position_without_exchange_balance_blocks_resume():
    result = reconcile_spot_positions(
        [],
        [LocalPositionView("ADAUSDT", 10.0, "p1")],
        {},
    )
    assert result.safe_to_resume is False
    assert result.issues[0].code == "LOCAL_POSITION_MISSING_ON_EXCHANGE"


def test_local_position_without_confirmed_protection_blocks_resume():
    result = reconcile_spot_positions(
        [ExchangeAsset("ADAUSDT", 10.0)],
        [LocalPositionView("ADAUSDT", 10.0, "p1")],
        {"ADAUSDT": False},
    )
    assert result.safe_to_resume is False
    assert result.has_unprotected is True


def test_matching_position_with_confirmed_protection_is_safe():
    result = reconcile_spot_positions(
        [ExchangeAsset("ADAUSDT", 10.0)],
        [LocalPositionView("ADAUSDT", 10.0, "p1")],
        {"ADAUSDT": True},
    )
    assert result.safe_to_resume is True
    assert result.issues == ()



def account_position(
    *,
    account_id="acct-1",
    position_id="pos-1",
    master_position_id="master-1",
    user_position_id="user-pos-1",
    symbol="ADAUSDT",
    quantity=10.0,
):
    return AccountLocalPositionView(
        account_id=account_id,
        position_id=position_id,
        master_position_id=master_position_id,
        user_position_id=user_position_id,
        symbol=symbol,
        quantity=quantity,
    )


def test_account_scoped_reconciliation_preserves_position_identity():
    result = reconcile_account_spot_positions(
        "acct-1",
        [ExchangeAsset("ADAUSDT", 10.0)],
        [account_position()],
        {"user-pos-1": True},
    )
    assert result.safe_to_resume is True
    assert result.issues == ()


def test_account_scope_mismatch_fails_closed():
    result = reconcile_account_spot_positions(
        "acct-1",
        [ExchangeAsset("ADAUSDT", 10.0)],
        [account_position(account_id="acct-2")],
        {"user-pos-1": True},
    )
    assert result.safe_to_resume is False
    assert result.issues[0].code == "ACCOUNT_SCOPE_MISMATCH"
    assert result.issues[0].account_id == "acct-1"
    assert result.issues[0].position_id == "pos-1"


def test_multiple_local_positions_for_same_spot_symbol_fail_closed():
    result = reconcile_account_spot_positions(
        "acct-1",
        [ExchangeAsset("ADAUSDT", 15.0)],
        [
            account_position(position_id="pos-1", user_position_id="user-pos-1", quantity=10.0),
            account_position(position_id="pos-2", user_position_id="user-pos-2", quantity=5.0),
        ],
        {"user-pos-1": True, "user-pos-2": True},
    )
    assert result.safe_to_resume is False
    assert any(i.code == "MULTIPLE_LOCAL_POSITIONS_SAME_SYMBOL" for i in result.issues)


def test_protection_is_checked_per_replica_position_identity():
    result = reconcile_account_spot_positions(
        "acct-1",
        [ExchangeAsset("ADAUSDT", 10.0)],
        [account_position()],
        {"user-pos-1": False},
    )
    assert result.safe_to_resume is False
    issue = next(i for i in result.issues if i.code == "UNPROTECTED_POSITION")
    assert issue.account_id == "acct-1"
    assert issue.position_id == "pos-1"


def test_account_scoped_orphan_does_not_depend_on_other_account_state():
    result = reconcile_account_spot_positions(
        "acct-1",
        [ExchangeAsset("ADAUSDT", 10.0)],
        [],
        {},
    )
    assert result.safe_to_resume is False
    assert result.issues[0].code == "ORPHAN_POSITION"
    assert result.issues[0].account_id == "acct-1"
