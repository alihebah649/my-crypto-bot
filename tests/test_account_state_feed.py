from datetime import datetime, timezone

import pytest

from core.account_connection import AccountConnection
from core.account_state_feed import (
    AccountEventKind,
    AccountStateEvent,
    UnconfiguredAccountStateFeed,
)


def test_event_is_scoped_to_account_connection():
    event = AccountStateEvent(
        event_id="evt-1",
        connection_id="user-20",
        kind=AccountEventKind.ORDER_UPDATE,
        payload={"symbol": "BTCUSDT", "status": "FILLED"},
        observed_at=datetime.now(timezone.utc),
    )

    assert event.connection_id == "user-20"
    assert event.kind is AccountEventKind.ORDER_UPDATE
    assert event.payload["status"] == "FILLED"


def test_event_requires_identity():
    with pytest.raises(ValueError):
        AccountStateEvent(
            event_id="",
            connection_id="user-20",
            kind=AccountEventKind.ORDER_UPDATE,
        )

    with pytest.raises(ValueError):
        AccountStateEvent(
            event_id="evt-2",
            connection_id="",
            kind=AccountEventKind.ORDER_UPDATE,
        )


def test_unconfigured_feed_fails_closed():
    connection = AccountConnection.paper_default()
    feed = UnconfiguredAccountStateFeed()

    with pytest.raises(RuntimeError, match="No account state feed configured"):
        feed.subscribe(connection, lambda event: None)

    assert feed.is_subscribed("paper-default") is False
