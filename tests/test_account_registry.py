import pytest

from core.account_connection import (
    AccountConnection,
    ConnectionState,
    CredentialReference,
)
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.execution_profile import AccountScope, ExecutionProfile


def _user(connection_id: str, *, state=ConnectionState.READY):
    profile = ExecutionProfile(
        profile_id=connection_id,
        exchange="BINANCE",
        account_scope=AccountScope.USER_SPOT,
        account_ref=connection_id,
        live_enabled=False,
    )
    return AccountConnection(
        connection_id=connection_id,
        profile=profile,
        credential=CredentialReference(f"vault://binance/{connection_id}"),
        state=state,
    )


def _master():
    profile = ExecutionProfile(
        profile_id="master",
        exchange="BINANCE",
        account_scope=AccountScope.BINANCE_LEAD_SPOT,
        account_ref="master",
        live_enabled=False,
    )
    return AccountConnection(
        connection_id="master",
        profile=profile,
        credential=CredentialReference("vault://binance/master"),
        state=ConnectionState.READY,
    )


def test_registry_returns_only_ready_enabled_followers():
    registry = AccountRegistry()
    registry.register(
        RegisteredAccount(_user("user-20"), AccountRole.FOLLOWER, 350.0)
    )
    registry.register(
        RegisteredAccount(
            _user("user-21", state=ConnectionState.DISCONNECTED),
            AccountRole.FOLLOWER,
            500.0,
        )
    )
    registry.register(
        RegisteredAccount(_user("user-22"), AccountRole.FOLLOWER, 700.0, copy_enabled=False)
    )
    registry.register(
        RegisteredAccount(_master(), AccountRole.MASTER, 1000.0)
    )

    followers = registry.followers()

    assert len(followers) == 1
    assert followers[0].connection_id == "user-20"
    assert followers[0].capital_basis == 350.0


def test_duplicate_connection_ids_are_rejected():
    registry = AccountRegistry()
    first = RegisteredAccount(_user("same"), AccountRole.FOLLOWER, 350.0)
    registry.register(first)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(RegisteredAccount(_user("same"), AccountRole.FOLLOWER, 400.0))


def test_replace_updates_capital_without_changing_connection_identity():
    registry = AccountRegistry()
    registry.register(
        RegisteredAccount(_user("user-20"), AccountRole.FOLLOWER, 350.0)
    )

    registry.replace(
        RegisteredAccount(_user("user-20"), AccountRole.FOLLOWER, 900.0)
    )

    follower = registry.followers()[0]
    assert follower.connection_id == "user-20"
    assert follower.capital_basis == 900.0


def test_remove_returns_registered_account():
    registry = AccountRegistry()
    account = RegisteredAccount(_user("user-20"), AccountRole.FOLLOWER, 350.0)
    registry.register(account)

    removed = registry.remove("user-20")

    assert removed == account
    assert registry.count() == 0
    assert registry.get("user-20") is None


def test_registry_does_not_store_market_data_fields():
    registry = AccountRegistry()
    registry.register(
        RegisteredAccount(_user("user-20"), AccountRole.FOLLOWER, 350.0)
    )

    assert not hasattr(registry.followers()[0], "price")
    assert not hasattr(registry.followers()[0], "klines")
