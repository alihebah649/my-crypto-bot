from core.dual_lane_position_gate import block_for_existing_position, requested_trade_modes


def test_dual_request_is_blocked_only_when_both_lanes_are_active():
    strategy={"signal":"BUY","scalp_signal":"BUY","swing_signal":"BUY","trade_mode":"SCALP"}
    assert requested_trade_modes(strategy) == {"SCALP","SWING"}
    assert block_for_existing_position(strategy, {"SWING"}) is False
    assert block_for_existing_position(strategy, {"SCALP"}) is False
    assert block_for_existing_position(strategy, {"SCALP","SWING"}) is True


def test_scalp_can_enter_when_only_swing_is_active():
    strategy={"signal":"BUY","scalp_signal":"BUY","swing_signal":"HOLD","trade_mode":"SCALP"}
    assert block_for_existing_position(strategy, {"SWING"}) is False
    assert block_for_existing_position(strategy, {"SCALP"}) is True


def test_swing_can_enter_when_only_scalp_is_active():
    strategy={"signal":"BUY","scalp_signal":"HOLD","swing_signal":"BUY","trade_mode":"SWING"}
    assert block_for_existing_position(strategy, {"SCALP"}) is False
    assert block_for_existing_position(strategy, {"SWING"}) is True


def test_single_legacy_lane_fallback_is_preserved():
    strategy={"signal":"BUY","trade_mode":"SCALP"}
    assert requested_trade_modes(strategy) == {"SCALP"}
    assert block_for_existing_position(strategy, set()) is False
    assert block_for_existing_position(strategy, {"SCALP"}) is True



def test_no_requested_lane_does_not_block():
    strategy={"signal":"HOLD","scalp_signal":"HOLD","swing_signal":"HOLD","trade_mode":"NONE"}
    assert requested_trade_modes(strategy) == set()
    assert block_for_existing_position(strategy, {"SCALP","SWING"}) is False
