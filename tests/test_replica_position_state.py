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



def test_master_position_and_user_position_linkage_are_deterministic():
    position = _position(
        master_position_id="MASTER-POS-1",
        user_position_id="USER-POS-20-MASTER-POS-1",
        idempotency_key="INTENT-OPEN-1:user-20:OPEN",
    )

    assert position.master_position_id == "MASTER-POS-1"
    assert position.user_position_id == "USER-POS-20-MASTER-POS-1"
    assert position.idempotency_key == "INTENT-OPEN-1:user-20:OPEN"


def test_state_store_persists_and_restores_positions(tmp_path):
    path = tmp_path / "replica-state.json"
    store = ReplicaPositionStateStore(str(path))
    store.register(_position(master_position_id="MASTER-POS-1"))

    restored = ReplicaPositionStateStore(str(path))

    position = restored.get("RP-1")
    assert position is not None
    assert position.master_position_id == "MASTER-POS-1"
    assert position.user_position_id == "RP-1"
    assert position.status is ReplicaPositionStatus.OPEN


def test_close_records_close_linkage_and_survives_restart(tmp_path):
    path = tmp_path / "replica-state.json"
    store = ReplicaPositionStateStore(str(path))
    store.register(_position(master_position_id="MASTER-POS-1"))

    closed = store.apply_close(
        position_id="RP-1",
        executed_quantity=0.175,
        close_intent_id="INTENT-CLOSE-1",
        master_close_position_id="MASTER-POS-1",
        exchange_order_id="PAPER-CLOSE-1",
    )

    assert closed.status is ReplicaPositionStatus.CLOSED
    assert closed.close_intent_id == "INTENT-CLOSE-1"
    assert closed.master_close_position_id == "MASTER-POS-1"
    assert closed.closed_at is not None
    assert closed.exchange_order_id == "PAPER-CLOSE-1"

    restored = ReplicaPositionStateStore(str(path))
    restored_position = restored.get("RP-1")
    assert restored_position is not None
    assert restored_position.status is ReplicaPositionStatus.CLOSED
    assert restored_position.close_intent_id == "INTENT-CLOSE-1"
    assert restored_position.exchange_order_id == "PAPER-CLOSE-1"


def test_trade_manager_position_status_is_the_authoritative_lifecycle():
    from trade_manager.models import PositionStatus

    position = _position(status=PositionStatus.HOLD)
    assert position.status is PositionStatus.HOLD
    assert ReplicaPositionStatus is PositionStatus



def test_restores_v1_replica_state_with_legacy_enum(tmp_path):
    path = tmp_path / "replica-v1.json"
    path.write_text(
        '{"version":1,"positions":[{"position_id":"RP-LEGACY","connection_id":"user-20",'
        '"source_intent_id":"INTENT-OPEN-1","symbol":"BTCUSDT","quantity":0.175,'
        '"remaining_quantity":0.175,"entry_price":100.0,"stop_loss_price":98.0,'
        '"status":{"__enum__":"ReplicaPositionStatus:OPEN"}}]}',
        encoding="utf-8",
    )

    store = ReplicaPositionStateStore(str(path))
    position = store.get("RP-LEGACY")

    assert position is not None
    assert position.status is ReplicaPositionStatus.OPEN
    assert position.master_position_id == "RP-LEGACY"
    assert position.user_position_id == "RP-LEGACY"


def test_idempotency_lookup_survives_restart(tmp_path):
    path = tmp_path / "replica-state.json"
    key = "INTENT-OPEN-1:user-20:OPEN"
    store = ReplicaPositionStateStore(str(path))
    store.register(_position(idempotency_key=key))

    restored = ReplicaPositionStateStore(str(path))
    position = restored.get_by_idempotency_key(key)

    assert position is not None
    assert position.position_id == "RP-1"
