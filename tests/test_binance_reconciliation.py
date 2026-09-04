from core.binance_reconciliation import (
    ExchangeAsset,
    LocalPositionView,
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
