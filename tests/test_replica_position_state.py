import pytest

from core.replica_position_state import (
    ReplicaPositionRecord,
    ReplicaPositionStateStore,
    ReplicaPositionStatus,
)


def _position(**overrides):
    data = {
        "position_id": "RP-1",
        "connection_id": "user-20",
        "source_intent_id": "INTENT-OPEN-1",
        "symbol": "BTCUSDT",
        "quantity": 0.175,
        "remaining_quantity": 0.175,
        "entry_price": 100.0,
        "stop_loss_price": 98.0,
    }
    data.update(overrides)
    return ReplicaPositionRecord(**data)


def test_registers_one_follower_position_against_source_intent():
    store = ReplicaPositionStateStore()
    position = _position()

    store.register(position)

    assert store.get("RP-1") == position
    assert store.by_source_intent("INTENT-OPEN-1") == (position,)
    assert store.active_for_account(
        connection_id="user-20",
        source_intent_id="INTENT-OPEN-1",
    ) == position


def test_close_fraction_is_based_on_remaining_account_position():
    position = _position()
    assert position.close_quantity(1.0) == pytest.approx(0.175)
    assert position.close_quantity(0.5) == pytest.approx(0.0875)


def test_partial_close_preserves_remaining_quantity():
    store = ReplicaPositionStateStore()
    store.register(_position())

    updated = store.apply_close(
        position_id="RP-1",
        executed_quantity=0.075,
    )

    assert updated.remaining_quantity == pytest.approx(0.1)
    assert updated.status is ReplicaPositionStatus.PARTIALLY_CLOSED
    assert updated.is_active is True


def test_full_close_marks_position_closed():
    store = ReplicaPositionStateStore()
    store.register(_position())

    updated = store.apply_close(
        position_id="RP-1",
        executed_quantity=0.175,
    )

    assert updated.remaining_quantity == pytest.approx(0.0)
    assert updated.status is ReplicaPositionStatus.CLOSED
    assert updated.is_active is False
    assert store.active_for_account(
        connection_id="user-20",
        source_intent_id="INTENT-OPEN-1",
    ) is None


def test_duplicate_position_id_is_rejected():
    store = ReplicaPositionStateStore()
    store.register(_position())

    with pytest.raises(ValueError, match="already exists"):
        store.register(_position())


def test_over_close_is_rejected_without_mutating_position():
    store = ReplicaPositionStateStore()
    original = _position()
    store.register(original)

    with pytest.raises(ValueError, match="exceeds remaining quantity"):
        store.apply_close(position_id="RP-1", executed_quantity=0.2)

    assert store.get("RP-1") == original


def test_position_state_does_not_depend_on_payment_or_market_data():
    position = _position()
    assert not hasattr(position, "settlement_state")
    assert not hasattr(position, "market_price")
