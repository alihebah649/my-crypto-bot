import pytest

from core.replication_delivery import (
    DeliveryState,
    ReplicationDeliveryLedger,
)


def test_same_intent_and_account_returns_same_delivery_record():
    ledger = ReplicationDeliveryLedger()

    first = ledger.register_new(
        intent_id="INTENT-1",
        connection_id="user-20",
        action="OPEN",
    )
    second = ledger.register_new(
        intent_id="INTENT-1",
        connection_id="user-20",
        action="OPEN",
    )

    assert first == second
    assert ledger.all() == (first,)


def test_different_accounts_get_independent_delivery_keys():
    ledger = ReplicationDeliveryLedger()

    user_20 = ledger.register_new(
        intent_id="INTENT-1",
        connection_id="user-20",
        action="OPEN",
    )
    user_21 = ledger.register_new(
        intent_id="INTENT-1",
        connection_id="user-21",
        action="OPEN",
    )

    assert user_20.delivery_key != user_21.delivery_key
    assert len(ledger.all()) == 2


def test_delivery_state_can_be_retried_without_changing_identity():
    ledger = ReplicationDeliveryLedger()
    record = ledger.register_new(
        intent_id="INTENT-1",
        connection_id="user-20",
        action="OPEN",
    )

    dispatched = ledger.transition(record.delivery_key, DeliveryState.DISPATCHED)
    failed = ledger.transition(record.delivery_key, DeliveryState.FAILED)

    assert dispatched.delivery_key == record.delivery_key
    assert failed.delivery_key == record.delivery_key
    assert failed.intent_id == "INTENT-1"
    assert failed.connection_id == "user-20"


def test_delivery_key_validation():
    with pytest.raises(ValueError):
        ReplicationDeliveryLedger.make_key(
            intent_id="",
            connection_id="user-20",
            action="OPEN",
        )

    with pytest.raises(ValueError):
        ReplicationDeliveryLedger.make_key(
            intent_id="INTENT-1",
            connection_id="",
            action="OPEN",
        )

    with pytest.raises(ValueError):
        ReplicationDeliveryLedger.make_key(
            intent_id="INTENT-1",
            connection_id="user-20",
            action="",
        )
