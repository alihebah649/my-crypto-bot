from core.paper_engine_health import snapshot


class FakeThread:
    def __init__(self, alive: bool):
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


def test_paper_engine_health_is_ok_for_live_recent_heartbeat():
    result = snapshot(
        FakeThread(True),
        {"state": "SLEEP", "started_at": 100.0},
        now=130.0,
        max_age_seconds=120.0,
    )

    assert result["status"] == "ok"
    assert result["engine_thread_alive"] is True
    assert result["heartbeat_age_seconds"] == 30.0
    assert result["paper_only"] is True


def test_paper_engine_health_is_unhealthy_when_thread_is_dead():
    result = snapshot(
        FakeThread(False),
        {"state": "SLEEP", "started_at": 100.0},
        now=130.0,
    )

    assert result["status"] == "unhealthy"


def test_paper_engine_health_is_unhealthy_when_heartbeat_is_stale():
    result = snapshot(
        FakeThread(True),
        {"state": "MARKET_CYCLE", "started_at": 100.0},
        now=251.0,
        max_age_seconds=120.0,
    )

    assert result["status"] == "unhealthy"
    assert result["heartbeat_age_seconds"] == 151.0
