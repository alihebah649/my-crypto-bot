from pathlib import Path

from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_runtime_uses_paper_persistence_dir_for_position_history(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )

    assert Path(runtime.repository.persistence_path) == tmp_path / "positions.json"
    assert Path(runtime.execution_adapter.state_path) == tmp_path / "paper_account.json"
    assert Path(runtime.facade.history_service.repository.path) == tmp_path / "position_history.json"

    runtime.facade.history_service.repository.save()
    assert (tmp_path / "position_history.json").exists()
