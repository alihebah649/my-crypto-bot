from core.brain_safety_gate import BrainSafetyGate


def test_hard_stop_overrides_brain_hold():
    result = BrainSafetyGate().evaluate("HOLD", hard_stop_triggered=True)
    assert result.action == "EXIT"
    assert result.authority == "HARD_STOP"
    assert result.allowed is True


def test_risk_lock_blocks_brain_buy():
    result = BrainSafetyGate().evaluate("BUY", risk_locked=True)
    assert result.action == "BLOCK"
    assert result.authority == "RISK"
    assert result.allowed is False


def test_exit_policy_overrides_brain_hold():
    result = BrainSafetyGate().evaluate("HOLD", policy_action="SELL")
    assert result.action == "EXIT"
    assert result.authority == "EXIT_POLICY"


def test_invalid_brain_action_is_blocked():
    result = BrainSafetyGate().evaluate("NUCLEAR_BUY")
    assert result.action == "BLOCK"
    assert result.allowed is False
