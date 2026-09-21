"""Credential-provider boundary for exchange account execution.

AccountConnection stores only an opaque reference. The trading engine can ask a
provider to resolve that reference at execution time, but this module never
persists, serializes, logs, or embeds credential material in account metadata.

A real vault/OAuth/Broker provider belongs to the application/infrastructure
layer and will be implemented later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from core.account_connection import CredentialReference
from core.execution_profile import ExecutionProfile


class CredentialProviderError(RuntimeError):
    """Base error for credential-resolution failures."""


class CredentialNotFoundError(CredentialProviderError):
    """Raised when an opaque credential reference cannot be resolved."""


class CredentialKind(str, Enum):
    API_KEY_SECRET = "API_KEY_SECRET"
    OAUTH_TOKEN = "OAUTH_TOKEN"
    BROKER_TOKEN = "BROKER_TOKEN"


@dataclass(frozen=True, slots=True)
class CredentialMaterial:
    """Ephemeral credential material held only in memory.

    Fields use repr=False so accidental logging of the object does not expose
    secrets. This object must never be persisted or included in metadata.
    """

    kind: CredentialKind
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    access_token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.kind is CredentialKind.API_KEY_SECRET:
            if not self.api_key or not self.api_secret:
                raise ValueError("API_KEY_SECRET requires api_key and api_secret")
        elif self.kind in {CredentialKind.OAUTH_TOKEN, CredentialKind.BROKER_TOKEN}:
            if not self.access_token:
                raise ValueError(f"{self.kind.value} requires access_token")

    @property
    def is_secret_material(self) -> bool:
        return True


class CredentialProvider(ABC):
    """Resolve opaque references into ephemeral, non-persisted credentials."""

    @abstractmethod
    def resolve(
        self,
        credential: CredentialReference,
        *,
        profile: ExecutionProfile,
    ) -> CredentialMaterial:
        """Resolve one account reference for one execution profile."""


class UnconfiguredCredentialProvider(CredentialProvider):
    """Safe default that refuses live credential resolution."""

    def resolve(
        self,
        credential: CredentialReference,
        *,
        profile: ExecutionProfile,
    ) -> CredentialMaterial:
        raise CredentialNotFoundError(
            f"No credential provider configured for {profile.exchange.upper()}"
        )


__all__ = [
    "CredentialKind",
    "CredentialMaterial",
    "CredentialNotFoundError",
    "CredentialProvider",
    "CredentialProviderError",
    "UnconfiguredCredentialProvider",
]
