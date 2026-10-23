"""Continuous mode with the jog of the plugin (constant speed while the key is held, as the lab's old alignment GUI):
motion controller rules with fake actuators and a fake clock."""
import pytest

from helpers import FakeClock, FakeJogPort, FakePort, app
from pymodaq_plugins_keyboardjog.core.actions import MoveAction
from pymodaq_plugins_keyboardjog.core.controller import ALIVE_PERIOD_S, JOG_STOP_GRACE_S, MotionController


@pytest.fixture
def rig():
    app()
    clock = FakeClock()
    ctrl = MotionController(clock=clock)
    ports = {'X': FakeJogPort('X'), 'Y': FakeJogPort('Y'), 'S': FakePort('S')}
    ctrl.set_ports(ports)
    ctrl.steps = {'X': 0.5, 'Y': 2.0, 'S': 1.0}
    ctrl.speeds = {'X': (0.1, 2.0), 'Y': (100.0, 1000.0)}
    ctrl.continuous = {'X', 'Y', 'S'}
    messages, finished = [], []
    ctrl.message.connect(messages.append)
    ctrl.move_finished.connect(lambda n, v: finished.append((n, v)))
    return ctrl, ports, clock, messages, finished


X_PLUS, X_MINUS = MoveAction('X', +1, 0), MoveAction('X', -1, 0)


def test_press_jogs_at_the_slow_speed_release_stops(rig):
    ctrl, ports, clock, _, finished = rig
    ctrl.press(X_PLUS)
    assert ports['X'].jogs == [(+1, 0.1)]
    assert ports['X'].moves == []                     # no step at all
    for _ in range(20):
        clock.advance(0.1)
        ctrl.tick()
    assert ports['X'].jogs == [(+1, 0.1)]             # held: nothing more sent but keep-alives
    assert ctrl.is_busy('X')
    ctrl.release(X_PLUS)
    assert ports['X'].stops == 1
    assert not ctrl.is_jogging('X')
    ports['X'].finish_jog(3.25)                       # move-done of the stop: the end point
    assert finished == [('X', 3.25)]
    assert not ctrl.is_busy('X')


def test_keep_alive_while_held(rig):
    ctrl, ports, clock, _, _ = rig
    ctrl.press(X_PLUS)
    for _ in range(int(2.0 / 0.05)):
        clock.advance(0.05)
        ctrl.tick()
    assert ports['X'].alive == pytest.approx(2.0 / ALIVE_PERIOD_S, abs=1)
    ctrl.release(X_PLUS)
    alive = ports['X'].alive
    clock.advance(2)
    ctrl.tick()
    assert ports['X'].alive == alive                  # none after the release


def test_shift_fast_ctrl_slow_div_10(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.set_multiplier(10.0)                         # Shift held before the press
    ctrl.press(X_MINUS)
    assert ports['X'].jogs[-1] == (-1, 2.0)
    ctrl.set_multiplier(1.0)                          # Shift released while held: back to slow at once
    assert ports['X'].jogs[-1] == (-1, 0.1)
    ctrl.set_multiplier(0.1)                          # Ctrl
    assert ports['X'].jogs[-1] == (-1, pytest.approx(0.01))
    assert ports['X'].stops == 0                      # speed changes are sent to the running jog


def test_inverted_keys(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.inverted = frozenset({'X'})
    ctrl.press(X_MINUS)                               # A on an inverted actuator: + (MV+ of the old GUI)
    assert ports['X'].jogs == [(+1, 0.1)]


def test_inverted_keys_step_mode(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.continuous = set()
    ctrl.inverted = frozenset({'X'})
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [-0.5]


def test_both_directions_held_last_wins_then_back(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.press(X_MINUS)
    ctrl.press(X_PLUS)
    assert ports['X'].jogs == [(-1, 0.1), (+1, 0.1)]
    ctrl.release(X_PLUS)                              # A still held: back to -
    assert ports['X'].jogs[-1] == (-1, 0.1)
    assert ports['X'].stops == 0
    ctrl.release(X_MINUS)
    assert ports['X'].stops == 1


def test_focus_loss_always_stops_the_jog(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.press(X_PLUS)
    ctrl.release_all(stop=False)                      # 'stop on focus loss' off: a jog is stopped anyway
    assert ports['X'].stops == 1
    assert not ctrl.is_jogging('X')


def test_new_ports_stop_the_jogs(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.press(X_PLUS)
    ctrl.set_ports({'Z': FakeJogPort('Z')})
    assert ports['X'].stops == 1


def test_leaving_continuous_mode_stops_the_jog(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.press(X_PLUS)
    ctrl.continuous = {'Y'}
    assert ports['X'].stops == 1


def test_jog_ended_by_the_actuator(rig):
    ctrl, ports, clock, messages, finished = rig
    ctrl.press(X_PLUS)
    ports['X'].finish_jog(25.0)                       # end of travel / dead man timeout of the plugin
    assert not ctrl.is_jogging('X')
    assert finished == [('X', 25.0)]
    assert any('ended by the actuator' in m for m in messages)
    clock.advance(1)
    ctrl.tick()
    assert ports['X'].jogs == [(+1, 0.1)]             # not restarted while the key is still held
    ctrl.release(X_PLUS)
    assert ports['X'].stops == 0


def test_press_again_during_the_stop_is_accepted(rig):
    """The jog command follows the stop in the hardware thread of the module: no overlap"""
    ctrl, ports, _, _, finished = rig
    ctrl.press(X_PLUS)
    ctrl.release(X_PLUS)
    ctrl.press(X_PLUS)
    assert ports['X'].jogs == [(+1, 0.1), (+1, 0.1)]
    ports['X'].finish_jog(1.0)                        # move-done of the first stop: the new jog goes on
    assert ctrl.is_jogging('X')
    assert finished == [('X', 1.0)]


def test_step_and_go_back_refused_while_jogging_or_stopping(rig):
    ctrl, ports, _, messages, _ = rig
    ctrl.press(X_PLUS)
    assert ctrl.move_to('X', 0.0) is False
    ctrl.release(X_PLUS)
    assert ctrl.move_to('X', 0.0) is False            # the end of the jog is not known yet
    ports['X'].finish_jog(2.0)
    assert ctrl.move_to('X', 0.0) is True


def test_lost_move_done_of_a_jog_stop(rig):
    ctrl, ports, clock, _, finished = rig
    ctrl.press(X_PLUS)
    ctrl.release(X_PLUS)
    clock.advance(JOG_STOP_GRACE_S + 0.1)
    ctrl.tick()
    assert finished == [('X', None)]
    assert ctrl.move_to('X', 0.0) is True


def test_moved_by_something_else_not_jogged(rig):
    ctrl, ports, _, messages, _ = rig
    ports['X'].external_moving = True
    ctrl.press(X_PLUS)
    assert ports['X'].jogs == []
    assert any('something else' in m for m in messages)
    assert not ctrl.is_held('X')


def test_not_initialized_not_jogged(rig):
    ctrl, ports, _, messages, _ = rig
    ports['X'].initialized = False
    ctrl.press(X_PLUS)
    assert ports['X'].jogs == []


def test_jog_failure_reported(rig):
    ctrl, ports, _, messages, _ = rig

    def fail(direction, speed):
        raise RuntimeError('boom')
    ports['X'].jog = fail
    ctrl.press(X_PLUS)
    assert any('jog failed' in m for m in messages)
    assert not ctrl.is_jogging('X')


def test_without_jog_the_continuous_mode_repeats_steps(rig):
    ctrl, ports, _, _, _ = rig
    ports['X'].jog_supported = False
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5] and ports['X'].jogs == []
    ports['X'].finish()
    assert ports['X'].moves == [0.5, 0.5]


def test_step_mode_actuator_with_jog_still_steps(rig):
    ctrl, ports, _, _, _ = rig
    ctrl.continuous = {'Y'}
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5] and ports['X'].jogs == []


def test_plus_minus_scale_the_speeds(rig):
    ctrl, ports, _, _, _ = rig
    changed = []
    ctrl.speeds_changed.connect(lambda n, s, f: changed.append((n, s, f)))
    ctrl.scale_steps(+1, 10.0, ['X', 'S'])
    assert ctrl.speeds['X'] == (pytest.approx(1.0), pytest.approx(20.0))
    assert ctrl.step('S') == 10.0                     # no jog: the step
    assert changed[0][0] == 'X'


def test_default_speeds_from_the_step(rig):
    ctrl, _, _, _, _ = rig
    ctrl.speeds = {}
    assert ctrl.slow_speed('X') == pytest.approx(5.0)     # 10 steps / s
    assert ctrl.fast_speed('X') == pytest.approx(50.0)
