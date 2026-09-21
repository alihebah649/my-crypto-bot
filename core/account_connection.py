"""Non-secret account connection boundary for future multi-account execution.

This module deliberately stores only opaque references to credentials. It never
accepts, serializes, logs, or persists API keys/secrets. A real vault/provider
will be supplied by the application layer later.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .execution_profile import AccountScope, ExecutionProfile


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    READY = "READY"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """Opaque identifier for credentials held outside the trading engine."""

    reference: str

    def __post_init__(self) -> None:
        if not str(self.reference).strip():
            raise ValueError("credential reference must not be empty")
        lowered = str(self.reference).lower()
        forbidden = ("api_key", "api_secret", "secret_key", "private_key")
        if any(token in lowered for token in forbidden):
            raise ValueError("credential reference must be opaque; do not embed secrets")


@dataclass(frozen=True, slots=True)
class AccountConnection:
    """Metadata binding an execution profile to externally stored credentials."""

    connection_id: str
    profile: ExecutionProfile
    credential: CredentialReference | None = None
    state: ConnectionState = ConnectionState.DISCONNECTED

    def __post_init__(self) -> None:
        if not str(self.connection_id).strip():
            raise ValueError("connection_id must not be empty")
        if self.profile.is_paper and self.credential is not None:
            raise ValueError("Paper connection must not require exchange credentials")
        if not self.profile.is_paper and self.credential is None:
            raise ValueError("Non-Paper connection requires an opaque credential reference")

    @property
    def is_live_candidate(self) -> bool:
        return not self.profile.is_paper and self.credential is not None

    def to_metadata(self) -> dict[str, str | bool]:
        data = self.profile.to_metadata()
        data.update({
            "connection_id": self.connection_id,
            "connection_state": self.state.value,
            "credential_reference": self.credential.reference if self.credential else "",
        })
        return data

    @classmethod
    def paper_default(cls) -> "AccountConnection":
        return cls(
            connection_id="paper-default",
            profile=ExecutionProfile.paper(),
            credential=None,
            state=ConnectionState.READY,
        )
