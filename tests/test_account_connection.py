from __future__ import annotations

import pytest

from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.execution_profile import AccountScope, ExecutionProfile


def test_paper_connection_has_no_credentials():
    connection = AccountConnection.paper_default()

    assert connection.profile.is_paper is True
    assert connection.credential is None
    assert connection.state is ConnectionState.READY
    assert connection.to_metadata()["credential_reference"] == ""


def test_live_account_uses_opaque_credential_reference_only():
    profile = ExecutionProfile(
        profile_id="user-binance-1",
        exchange="BINANCE",
        account_scope=AccountScope.USER_SPOT,
        account_ref="user-opaque-1",
        live_enabled=False,
    )
    connection = AccountConnection(
        connection_id="conn-1",
        profile=profile,
        credential=CredentialReference("vault://binance/user-opaque-1"),
    )

    assert connection.is_live_candidate is True
    assert connection.to_metadata()["credential_reference"] == "vault://binance/user-opaque-1"


@pytest.mark.parametrize(
    "value",
    ["my_api_key_value", "api_secret=abc", "private_key_ref"],
)
def test_credential_reference_rejects_embedded_secret_like_values(value):
    with pytest.raises(ValueError, match="opaque"):
        CredentialReference(value)


def test_non_paper_connection_cannot_omit_credentials():
    profile = ExecutionProfile(
        profile_id="lead-1",
        exchange="BINANCE",
        account_scope=AccountScope.BINANCE_LEAD_SPOT,
        live_enabled=False,
    )

    with pytest.raises(ValueError, match="requires an opaque credential"):
        AccountConnection(connection_id="conn-2", profile=profile)
