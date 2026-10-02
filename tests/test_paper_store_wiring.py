"""Regression test for the active Shadow entrypoint's durable report wiring."""

import importlib
import runpy


def test_active_shadow_entrypoint_binds_paper_outcome_store(monkeypatch):
    postgres_module = importlib.import_module("core.postgres_evidence_store")

    class FakeStore:
        def __init__(self, *args, **kwargs):
            self.last_error = None

        def summary(self):
            return {"backend": "postgres", "record_count": 123}

        def append(self, record):
            return True

        def read_all(self):
            return []

        def read_time_range(self, *args, **kwargs):
            return []

    monkeypatch.setattr(postgres_module, "database_url_from_env", lambda: "postgresql://fake")
    monkeypatch.setattr(postgres_module, "PostgresEvidenceStore", FakeStore)

    namespace = runpy.run_path("shadow_main.py", run_name="shadow_main_test")

    legacy = importlib.import_module("shadow_main_legacy")
    assert namespace["_paper_outcome_store"] is not None
    assert legacy._paper_outcome_store is namespace["_paper_outcome_store"]
