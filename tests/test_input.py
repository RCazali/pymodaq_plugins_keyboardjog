"""Keyboard input source: Qt key events -> actions."""
import pytest
from qtpy import QtCore

from helpers import app, key_event
from pymodaq_plugins_keyboardjog.core.input import KeyboardInput
from pymodaq_plugins_keyboardjog.core.keys import KEY_LEFT, KEY_RIGHT
from pymodaq_plugins_keyboardjog.core.actions import MoveAction

Qt = QtCore.Qt


@pytest.fixture
def kb():
    app()
    kb = KeyboardInput()
    kb.set_keymap({KEY_LEFT: MoveAction('X', -1, 0), KEY_RIGHT: MoveAction('X', +1, 0)})
    log = []
    kb.move_pressed.connect(lambda a: log.append(('press', a.actuator, a.direction)))
    kb.move_released.connect(lambda a: log.append(('release', a.actuator, a.direction)))
    kb.step_scale_requested.connect(lambda s: log.append(('scale', s)))
    kb.multiplier_changed.connect(lambda m: log.append(('mult', m)))
    kb.reset_requested.connect(lambda: log.append(('reset',)))
    return kb, log


def test_press_release(kb):
    kb, log = kb
    assert kb.key_press(key_event('press', Qt.Key_Right))
    assert kb.key_release(key_event('release', Qt.Key_Right))
    assert log == [('press', 'X', 1), ('release', 'X', 1)]


def test_os_auto_repeat_is_ignored(kb):
    kb, log = kb
    kb.key_press(key_event('press', Qt.Key_Left))
    for _ in range(5):
        assert kb.key_release(key_event('release', Qt.Key_Left, auto_repeat=True))   # consumed, ignored
        assert kb.key_press(key_event('press', Qt.Key_Left, auto_repeat=True))
    assert log == [('press', 'X', -1)]
    assert kb.key_press(key_event('press', Qt.Key_Plus, auto_repeat=True))
    assert log == [('press', 'X', -1)]


def test_unbound_keys_are_not_consumed(kb):
    kb, log = kb
    assert not kb.key_press(key_event('press', Qt.Key_Q))
    assert not kb.key_release(key_event('release', Qt.Key_Q))
    assert log == []


def test_step_keys(kb):
    kb, log = kb
    kb.key_press(key_event('press', Qt.Key_Plus))
    kb.key_press(key_event('press', Qt.Key_Minus))
    kb.key_press(key_event('press', Qt.Key_Equal))
    assert log == [('scale', 1), ('scale', -1), ('scale', 1)]


def test_modifiers(kb):
    kb, log = kb
    kb.key_press(key_event('press', Qt.Key_Shift, Qt.ShiftModifier))
    assert kb.multiplier == 10
    kb.key_press(key_event('press', Qt.Key_Right, Qt.ShiftModifier))
    kb.key_release(key_event('release', Qt.Key_Shift))
    assert kb.multiplier == 1
    kb.key_press(key_event('press', Qt.Key_Control, Qt.ControlModifier))
    assert kb.multiplier == pytest.approx(0.1)
    kb.key_press(key_event('press', Qt.Key_Shift, Qt.ControlModifier | Qt.ShiftModifier))
    assert kb.multiplier == 1
    assert [e for e in log if e[0] == 'mult'] == [('mult', 10), ('mult', 1), ('mult', pytest.approx(0.1)),
                                                  ('mult', 1)]


def test_reset_forgets_held_keys(kb):
    kb, log = kb
    kb.key_press(key_event('press', Qt.Key_Right, Qt.ShiftModifier))
    kb.reset()
    assert kb.held == {} and kb.multiplier == 1
    assert log[-1] == ('reset',)
    log.clear()
    kb.key_release(key_event('release', Qt.Key_Right))   # late release: nothing to release
    assert log == []


def test_digits_select_groups(kb):
    kb, log = kb
    selections = []
    kb.select_requested.connect(selections.append)
    assert kb.key_press(key_event('press', Qt.Key_3))
    assert kb.key_press(key_event('press', Qt.Key_1, Qt.KeypadModifier))
    assert kb.key_press(key_event('press', Qt.Key_9, auto_repeat=True))       # auto-repeat ignored
    assert selections == [3, 1]
    assert not kb.key_press(key_event('press', Qt.Key_0))


def test_movement_keys_follow_the_selection(kb):
    kb, log = kb
    from pymodaq_plugins_keyboardjog.core.model import Group, direction_map
    kb.set_keymap({})
    kb.set_direction_map(direction_map(Group(['Y']), 1), 'wasd')
    kb.key_press(key_event('press', Qt.Key_W))
    kb.set_direction_map(direction_map(Group(['Z']), 2))                       # held movement key released
    assert log[-2:] == [('press', 'Y', 1), ('release', 'Y', 1)]
    kb.key_press(key_event('press', Qt.Key_A))
    assert log[-1] == ('press', 'Z', -1)
    assert not kb.key_press(key_event('press', Qt.Key_Left))                   # arrows off in 'wasd'
    kb.set_direction_map(direction_map(Group(['Z']), 2), 'arrows')
    assert kb.key_press(key_event('press', Qt.Key_Left))
    assert not kb.key_press(key_event('press', Qt.Key_W))


def test_new_keymap_releases_held_keys(kb):
    kb, log = kb
    kb.key_press(key_event('press', Qt.Key_Right))
    kb.set_keymap({})
    assert log[-1] == ('release', 'X', 1)
    assert not kb.key_press(key_event('press', Qt.Key_Right))
