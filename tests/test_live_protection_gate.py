from core.live_protection_gate import ProtectionState, evaluate_protection_gate


def test_paper_mode_never_requires_live_exchange_protection():
    result = evaluate_protection_gate(
        live_mode=False,
        buy_filled=True,
        protection_confirmed=False,
    )
    assert result.allowed is True
    assert result.state is ProtectionState.PROTECTED


def test_live_filled_buy_waits_for_exchange_confirmation():
    result = evaluate_protection_gate(
        live_mode=True,
        buy_filled=True,
        protection_confirmed=False,
    )
    assert result.allowed is False
    assert result.state is ProtectionState.PROTECTING


def test_live_filled_buy_is_safe_only_after_confirmation():
    result = evaluate_protection_gate(
        live_mode=True,
        buy_filled=True,
        protection_confirmed=True,
    )
    assert result.allowed is True
    assert result.state is ProtectionState.PROTECTED


def test_unfilled_live_buy_is_not_protected():
    result = evaluate_protection_gate(
        live_mode=True,
        buy_filled=False,
        protection_confirmed=True,
    )
    assert result.allowed is False
    assert result.state is ProtectionState.UNPROTECTED
