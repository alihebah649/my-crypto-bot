from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_history_uses_runtime_persistence_dir(tmp_path):
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, persistence_dir=str(tmp_path))

    assert runtime.facade.history_service.repository.path == str(
        tmp_path / "position_history.json"
    )
