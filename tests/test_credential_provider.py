import pytest

from core.account_connection import CredentialReference
from core.credential_provider import (
    CredentialKind,
    CredentialMaterial,
    CredentialNotFoundError,
    UnconfiguredCredentialProvider,
)
from core.execution_profile import AccountScope, ExecutionProfile


def _profile():
    return ExecutionProfile(
        profile_id="user-binance-1",
        exchange="BINANCE",
        account_scope=AccountScope.USER_SPOT,
        account_ref="user-1",
        live_enabled=False,
    )


def test_api_key_secret_material_requires_both_values():
    with pytest.raises(ValueError):
        CredentialMaterial(CredentialKind.API_KEY_SECRET, api_key="key")


def test_oauth_and_broker_material_require_access_token():
    with pytest.raises(ValueError):
        CredentialMaterial(CredentialKind.OAUTH_TOKEN)

    with pytest.raises(ValueError):
        CredentialMaterial(CredentialKind.BROKER_TOKEN)


def test_secret_material_repr_is_redacted():
    material = CredentialMaterial(
        CredentialKind.API_KEY_SECRET,
        api_key="super-secret-key",
        api_secret="super-secret-value",
    )
    rendered = repr(material)

    assert "super-secret-key" not in rendered
    assert "super-secret-value" not in rendered
    assert "CredentialKind.API_KEY_SECRET" in rendered


def test_unconfigured_provider_fails_closed():
    provider = UnconfiguredCredentialProvider()
    reference = CredentialReference("vault://binance/user-1")

    with pytest.raises(CredentialNotFoundError, match="No credential provider configured"):
        provider.resolve(reference, profile=_profile())


def test_credential_reference_remains_separate_from_secret_material():
    reference = CredentialReference("vault://binance/user-1")
    material = CredentialMaterial(
        CredentialKind.API_KEY_SECRET,
        api_key="key",
        api_secret="secret",
    )

    assert reference.reference == "vault://binance/user-1"
    assert material.is_secret_material is True
