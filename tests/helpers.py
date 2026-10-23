"""Test helpers: the QApplication, an event-loop wait, fake actuators, real Mock DAQ_Move modules."""
import os
import sys
import time
import warnings

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform == 'win32':  # the offscreen platform finds no font on Windows: text sizes would be meaningless
    os.environ.setdefault('QT_QPA_FONTDIR', os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts'))
warnings.filterwarnings('ignore')

from qtpy import QtCore, QtGui, QtWidgets  # noqa: E402

from pymodaq_plugins_keyboardjog.core.ports import ActuatorPort  # noqa: E402

_app = None


def app():
    """The QApplication, created like PyMoDAQ does"""
    global _app
    _app = QtWidgets.QApplication.instance()
    if _app is None:
        try:
            from pymodaq_gui.qt_utils import mkQApp          # pymodaq_gui >= 5.2
        except ImportError:
            from pymodaq_gui.utils.utils import mkQApp       # pymodaq_gui 5.0 / 5.1
        _app = mkQApp('pytest')
    return _app


def wait(pred=lambda: False, timeout=10.0, step=0.005):
    a = app()
    t0 = time.time()
    while time.time() - t0 < timeout:
        a.processEvents()
        if pred():
            return True
        time.sleep(step)
    a.processEvents()
    return pred()


def key_event(kind, key, modifiers=None, auto_repeat=False, text=''):
    if modifiers is None:
        modifiers = QtCore.Qt.NoModifier
    event_type = QtCore.QEvent.KeyPress if kind == 'press' else QtCore.QEvent.KeyRelease
    return QtGui.QKeyEvent(event_type, key, modifiers, text, auto_repeat)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakePort(ActuatorPort):
    """An actuator whose moves end when the test calls finish()"""

    def __init__(self, name, units='mm'):
        self.name = name
        self._units = units
        self.position = 0.0
        self.moves = []
        self.stops = 0
        self.moving = False
        self.external_moving = False
        self.initialized = True
        self.on_value = None
        self.on_done = None

    def units(self):
        return self._units

    def is_initialized(self):
        return self.initialized

    def is_moving(self):
        return self.moving or self.external_moving

    def move_rel(self, delta):
        self.moves.append(delta)
        self.moving = True
        self._target = self.position + delta

    def move_abs(self, value):
        self.moves.append(('abs', value))
        self.moving = True
        self._target = value

    def stop(self):
        self.stops += 1

    def finish(self):
        if self.moving:
            self.moving = False
            self.position = self._target
            if self.on_done is not None:
                self.on_done(self.position)
            if self.on_value is not None:
                self.on_value(self.position)


class FakeJogPort(FakePort):
    """An actuator whose plugin implements the continuous jog; the move-done of a stop comes when the test calls
    finish_jog()"""

    def __init__(self, name, units='mm'):
        super().__init__(name, units)
        self.jogs = []
        self.alive = 0
        self.jog_supported = True
        self.jogging = False

    def supports_jog(self):
        return self.jog_supported

    def jog(self, direction, speed):
        self.jogs.append((direction, speed))
        self.jogging = True

    def jog_alive(self):
        self.alive += 1

    def stop(self):
        self.stops += 1
        self.jogging = False

    def finish_jog(self, position=None):
        """The plugin signals the end of the jog (after a stop, or by itself)"""
        self.jogging = False
        if position is not None:
            self.position = position
        if self.on_done is not None:
            self.on_done(self.position)


def find_param(root, name):
    for c in root.children():
        if c.name() == name:
            return c
        found = find_param(c, name)
        if found is not None:
            return found
    return None


def make_mock_move(title, axis='Y', tau_ms=50):
    """A real DAQ_Move with the Mock actuator of pymodaq_plugins_mock, initialized"""
    from pymodaq.control_modules.daq_move import DAQ_Move
    mv = DAQ_Move(None, title=title)
    mv.actuator = 'Mock'
    hw = mv.settings.child(getattr(mv, '_hw_settings_name', 'move_settings'))  # 5.1: move_settings, 5.3: actuator_settings
    find_param(hw, 'axis').setValue(axis)
    find_param(hw, 'tau').setValue(tau_ms)
    inits = []
    mv.init_signal.connect(inits.append)
    mv.init_hardware(True)
    assert wait(lambda: inits, 20), f'{title} not initialized'
    assert inits[-1], f'{title} init failed'
    wait(lambda: mv.move_done_bool, 2)
    return mv


def set_tau(mv, tau_ms):
    hw = mv.settings.child(getattr(mv, '_hw_settings_name', 'move_settings'))
    find_param(hw, 'tau').setValue(tau_ms)
    wait(timeout=0.1)


class FakeDashboard:
    """Just what CustomExt needs to build its modules manager"""

    def __init__(self, actuators):
        self.actuators_modules = list(actuators)
        self.detector_modules = []
        self.experiment_manager = None
        self.state_manager = None
        self.splash_sc = None
