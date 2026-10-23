"""The extension with real DAQ_Move modules whose plugin implements the continuous jog (JogMock of
pymodaq_plugins_hhglab: a simulated axis, no hardware): constant speed while the key is held, Shift = fast, stop at
the release, the end point in the history, keys inverted, focus loss."""
import pytest
from qtpy import QtCore, QtWidgets

pytest.importorskip('pymodaq')
pytest.importorskip('pymodaq_plugins_hhglab')

from helpers import FakeDashboard, app, key_event, wait  # noqa: E402
from pymodaq_plugins_keyboardjog.core.model import VERTICAL, JogSetup  # noqa: E402

pytestmark = pytest.mark.pymodaq
Qt = QtCore.Qt
NAMES = ('Jog X', 'Jog Y')


def make_jog_move(title):
    from pymodaq.control_modules.daq_move import DAQ_Move
    mv = DAQ_Move(None, title=title)
    mv.actuator = 'JogMock'
    inits = []
    mv.init_signal.connect(inits.append)
    mv.init_hardware(True)
    assert wait(lambda: inits, 20) and inits[-1], f'{title} not initialized'
    wait(lambda: mv.move_done_bool, 2)
    return mv


def value_of(mv) -> float:
    """DAQ_Move.current_value recurses forever in PyMoDAQ 5.3.4-5.3.8 when its value has no origin"""
    value = mv._current_value
    return float(value.value()) if hasattr(value, 'value') else float(value)


@pytest.fixture(autouse=True)
def qwerty_labels(monkeypatch):
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    monkeypatch.setattr(kj, 'is_azerty', lambda: False)


@pytest.fixture(scope='module')
def modules():
    app()
    mods = [make_jog_move(name) for name in NAMES]
    yield mods
    for m in mods:
        m.quit_fun()
    wait(timeout=1.5)


@pytest.fixture
def ext(modules, tmp_path, monkeypatch):
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq_gui.utils.dock import DockArea
    monkeypatch.setattr(kj, 'default_folder', lambda config=None: tmp_path / 'setups')
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    ext = kj.KeyboardJog(area, FakeDashboard(modules))
    win.show()
    ext.mainwindow.activateWindow()
    ext.panel.setFocus(Qt.OtherFocusReason)
    assert wait(lambda: ext.panel.armed, 5)
    ext._write_tree(JogSetup(pair_numbers={'Jog X': 1, 'Jog Y': 1}, axes={'Jog Y': VERTICAL},
                             continuous=list(NAMES), slow_speeds={'Jog X': 2.0, 'Jog Y': 2.0},
                             fast_speeds={'Jog X': 8.0, 'Jog Y': 8.0}, inverted=['Jog Y']))
    ext.apply_settings()
    assert wait(lambda: all(ext.controller.is_native(n) for n in NAMES), 5), 'jog of the plugin not detected'
    yield ext
    ext.quit_fun()
    win.close()
    wait(timeout=0.3)


def press(ext, key, modifiers=None):
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('press', key, modifiers))


def release(ext, key, modifiers=None):
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('release', key, modifiers))


def hold(ext, key, seconds, modifiers=None):
    press(ext, key, modifiers)
    wait(timeout=seconds)
    release(ext, key, modifiers)


def settle(ext, name):
    assert wait(lambda: not ext.controller.is_busy(name), 6), f'{name} still busy after the release'


def test_hold_moves_at_constant_speed_and_stops_at_release(ext, modules):
    mx = modules[0]
    start = value_of(mx)
    press(ext, Qt.Key_D)
    assert wait(lambda: ext.controller.is_jogging('Jog X'), 2)
    wait(timeout=0.5)
    moving = value_of(mx)
    assert moving > start                                # values arrive while the key is held
    wait(timeout=0.5)
    release(ext, Qt.Key_D)
    settle(ext, 'Jog X')
    end = value_of(mx)
    assert end - start == pytest.approx(2.0 * 1.0, abs=0.5)    # about 1 s at 2 mm/s
    wait(timeout=0.4)
    assert value_of(mx) == pytest.approx(end)          # stopped
    assert ext.values['Jog X'] == pytest.approx(end)
    assert mx.move_done_bool


def test_shift_is_the_fast_speed(ext, modules):
    mx = modules[0]
    start = value_of(mx)
    hold(ext, Qt.Key_D, 0.5, Qt.ShiftModifier)
    settle(ext, 'Jog X')
    assert value_of(mx) - start == pytest.approx(8.0 * 0.5, abs=1.0)


def test_end_point_recorded_in_the_history(ext, modules):
    before = len(ext.history.points(['Jog X', 'Jog Y']))
    hold(ext, Qt.Key_A, 0.3)
    settle(ext, 'Jog X')
    points = ext.history.points(['Jog X', 'Jog Y'])
    assert len(points) > before
    assert points[-1][1] == pytest.approx(value_of(modules[0]))


def test_inverted_actuator(ext, modules):
    my = modules[1]
    start = value_of(my)
    hold(ext, Qt.Key_W, 0.4)                             # W on an inverted actuator: -
    settle(ext, 'Jog Y')
    assert value_of(my) < start - 0.3


def test_focus_loss_stops_the_jog(ext, modules):
    mx = modules[0]
    press(ext, Qt.Key_D)
    assert wait(lambda: ext.controller.is_jogging('Jog X'), 2)
    other = QtWidgets.QLineEdit()
    other.show()
    other.activateWindow()
    other.setFocus()
    assert wait(lambda: not ext.panel.armed, 5)
    settle(ext, 'Jog X')
    end = value_of(mx)
    wait(timeout=0.4)
    assert value_of(mx) == pytest.approx(end)
    other.close()


def test_dead_man_when_the_keep_alive_stops(ext, modules, monkeypatch):
    """A frozen extension (no keep-alive) does not leave the motor running: the plugin stops it"""
    from pymodaq_plugins_hhglab.daq_move_plugins.daq_move_JogMock import DAQ_Move_JogMock  # noqa: F401
    mx = modules[0]
    mx.settings.child(getattr(mx, '_hw_settings_name', 'move_settings'), 'jog', 'alive_timeout_s').setValue(0.6)
    port = ext.ports['Jog X']
    press(ext, Qt.Key_D)
    assert wait(lambda: ext.controller.is_jogging('Jog X'), 2)
    wait(timeout=0.7)                                     # one keep-alive sent: the short timeout is armed
    monkeypatch.setattr(port, 'jog_alive', lambda: None)  # the extension goes silent, the key still held
    assert wait(lambda: not ext.controller.is_jogging('Jog X'), 4), 'the plugin did not stop the jog'
    release(ext, Qt.Key_D)
    settle(ext, 'Jog X')
