"""Motion controller rules with fake actuators and a fake clock."""
import pytest

from helpers import FakeClock, FakePort, app
from pymodaq_plugins_keyboardjog.core.actions import MoveAction
from pymodaq_plugins_keyboardjog.core.controller import MotionController


@pytest.fixture
def rig():
    app()
    clock = FakeClock()
    ctrl = MotionController(clock=clock)
    ports = {n: FakePort(n) for n in ('X', 'Y')}
    ctrl.set_ports(ports)
    ctrl.steps = {'X': 0.5, 'Y': 2.0}
    messages = []
    ctrl.message.connect(messages.append)
    return ctrl, ports, clock, messages


X_PLUS = MoveAction('X', +1, 0)
X_MINUS = MoveAction('X', -1, 0)


def test_step_mode_one_press_one_step(rig):
    ctrl, ports, clock, _ = rig
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5]
    ports['X'].finish()
    clock.advance(1)
    ctrl.tick()
    assert ports['X'].moves == [0.5]          # holding does nothing more
    ctrl.release(X_PLUS)
    ctrl.press(X_MINUS)
    assert ports['X'].moves == [0.5, -0.5]
    assert ports['Y'].moves == []


def test_no_queue_press_while_moving_is_dropped(rig):
    ctrl, ports, clock, messages = rig
    ctrl.press(X_PLUS)
    ctrl.release(X_PLUS)
    ctrl.press(X_PLUS)                        # previous step not done
    ctrl.release(X_PLUS)
    assert ports['X'].moves == [0.5]
    assert any('still moving' in m for m in messages)
    ports['X'].finish()
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5, 0.5]


def test_actuator_moved_by_something_else_is_not_moved(rig):
    ctrl, ports, clock, messages = rig
    ports['X'].external_moving = True
    ctrl.press(X_PLUS)
    assert ports['X'].moves == []
    assert any('something else' in m for m in messages)
    ports['X'].initialized = False
    ports['X'].external_moving = False
    ctrl.release(X_PLUS)
    ctrl.press(X_PLUS)
    assert ports['X'].moves == []


def test_continuous_mode_repeats_after_move_done_only(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'X', 'Y'}
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5]
    for _ in range(5):                        # no move-done: nothing more is sent
        clock.advance(0.1)
        ctrl.tick()
    assert ports['X'].moves == [0.5]
    ports['X'].finish()                       # move done -> next step at once
    assert ports['X'].moves == [0.5, 0.5]
    ports['X'].finish()
    assert len(ports['X'].moves) == 3
    ctrl.release(X_PLUS)                      # release: the step in progress finishes, no new one
    ports['X'].finish()
    clock.advance(1)
    ctrl.tick()
    assert len(ports['X'].moves) == 3


def test_continuous_min_interval(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'X', 'Y'}
    ctrl.min_interval_s = 0.2
    ctrl.press(X_PLUS)
    ports['X'].finish()
    assert len(ports['X'].moves) == 1
    clock.advance(0.1)
    ctrl.tick()
    assert len(ports['X'].moves) == 1
    clock.advance(0.15)
    ctrl.tick()
    assert len(ports['X'].moves) == 2


def test_multiplier_only_in_continuous_mode(rig):
    ctrl, ports, clock, _ = rig
    ctrl.set_multiplier(10.0)
    ctrl.press(X_PLUS)
    assert ports['X'].moves == [0.5]          # step mode: modifiers ignored
    ctrl.release(X_PLUS)
    ports['X'].finish()
    ctrl.continuous = {'X', 'Y'}
    ctrl.set_multiplier(10.0)
    ctrl.press(X_PLUS)
    ports['X'].finish()
    ctrl.set_multiplier(0.1)
    ports['X'].finish()
    assert ports['X'].moves == pytest.approx([0.5, 5.0, 5.0, 0.05])
    assert ctrl.step('X') == 0.5              # the stored step is unchanged


def test_last_direction_wins_and_both_axes_move(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'X', 'Y'}
    ctrl.press(X_PLUS)
    ctrl.press(MoveAction('Y', -1, 0))
    ctrl.press(X_MINUS)                       # X busy: dropped now, but held
    ports['X'].finish()
    ports['Y'].finish()
    assert ports['X'].moves == [0.5, -0.5]
    assert ports['Y'].moves == [-2.0, -2.0]
    ctrl.release(X_MINUS)
    ports['X'].finish()
    assert ports['X'].moves == [0.5, -0.5, 0.5]   # X+ still held


def test_release_all_stops_pending_moves(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'X', 'Y'}
    ctrl.press(X_PLUS)
    ctrl.release_all(stop=True)
    assert ports['X'].stops == 1 and ports['Y'].stops == 0
    ports['X'].finish()
    assert ports['X'].moves == [0.5]          # nothing held anymore
    assert not ctrl.is_held('X')
    ctrl.press(X_PLUS)
    ctrl.release_all(stop=False)
    assert ports['X'].stops == 1


def test_move_timeout_releases_the_actuator(rig):
    ctrl, ports, clock, messages = rig
    ctrl.move_timeout_s = 2.0
    ctrl.press(X_PLUS)
    ports['X'].moving = False                 # move-done lost
    clock.advance(2.5)
    ctrl.tick()
    assert not ctrl.is_busy('X')
    assert any('no move-done' in m for m in messages)
    ctrl.release(X_PLUS)
    ctrl.press(X_PLUS)
    assert len(ports['X'].moves) == 2


def test_scale_steps(rig):
    ctrl, ports, clock, _ = rig
    changes = []
    ctrl.step_changed.connect(lambda n, v: changes.append((n, v)))
    ctrl.scale_steps(+1, 10, ['X'])
    assert ctrl.step('X') == pytest.approx(5.0) and ctrl.step('Y') == 2.0
    ctrl.scale_steps(-1, 10, ['X', 'Y'])
    assert ctrl.step('X') == pytest.approx(0.5) and ctrl.step('Y') == pytest.approx(0.2)
    assert [n for n, _ in changes] == ['X', 'X', 'Y']


def test_mode_change_releases_held_actions(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'X', 'Y'}
    ctrl.press(X_PLUS)
    ctrl.press(MoveAction('Y', +1, 0))
    ctrl.continuous = {'Y'}                   # X back to step mode: released; Y unchanged: still held
    assert not ctrl.is_held('X') and ctrl.is_held('Y')


def test_continuous_is_per_actuator(rig):
    ctrl, ports, clock, _ = rig
    ctrl.continuous = {'Y'}
    ctrl.press(X_PLUS)
    ctrl.press(MoveAction('Y', +1, 0))
    for _ in range(3):
        ports['X'].finish()
        ports['Y'].finish()
    assert ports['X'].moves == [0.5]          # step mode
    assert ports['Y'].moves == [2.0] * 4      # continuous


def test_move_to_follows_the_no_queue_rule(rig):
    ctrl, ports, clock, messages = rig
    started, finished = [], []
    ctrl.move_started.connect(started.append)
    ctrl.move_finished.connect(lambda n, v: finished.append((n, v)))
    assert ctrl.move_to('X', 3.0)
    assert not ctrl.move_to('X', 4.0)         # still moving: dropped
    assert ports['X'].moves == [('abs', 3.0)] and ctrl.is_busy('X')
    ports['X'].finish()
    assert not ctrl.is_busy('X')
    assert started == ['X'] and finished == [('X', 3.0)]


def test_move_finished_for_moves_of_any_origin(rig):
    ctrl, ports, clock, _ = rig
    finished = []
    ctrl.move_finished.connect(lambda n, v: finished.append((n, v)))
    ports['Y'].on_done(7.5)                   # moved by the Dashboard or a scan
    assert finished == [('Y', 7.5)]
    ctrl.move_timeout_s = 1.0
    ctrl.press(X_PLUS)
    clock.advance(2)
    ctrl.tick()                               # timeout: finished with an unknown value
    assert finished[-1] == ('X', None)
