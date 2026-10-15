"""The real PyMoDAQ Dashboard discovers and loads the extension through the ``pymodaq.extensions`` entry point.

* PyMoDAQ 5.1: preset file + ``DashBoard.load_extension_from_name('Keyboard Jog')``
* PyMoDAQ >= 5.2: experiment file + ``load_dashboard_with_experiment(..., 'KEYBOARDJOG')``

The preset / experiment with Mock actuators (tools/mock_config.py) is written in the PyMoDAQ folder and removed at the
end; the setups go to a temporary folder.
"""
import os
import shutil

import pytest
from qtpy import QtCore, QtWidgets

pytest.importorskip('pymodaq')
pytest.importorskip('pymodaq_plugins_mock')

from helpers import app, key_event, wait  # noqa: E402

pytestmark = pytest.mark.pymodaq
NAME = 'kj_pytest_dashboard'
MOVES = (('Jog X', 'Y'), ('Jog Y', 'Y'))


def test_extension_is_discovered():
    from pymodaq.extensions.utils import get_extensions
    extensions = get_extensions()
    if isinstance(extensions, dict):          # PyMoDAQ 5.3: {ExtensionEnum: Extension(name, class_name, klass)}
        names = [e.name for e in extensions.values()]
    else:                                     # 5.1: list of dicts
        names = [e['name'] for e in extensions]
    assert 'Keyboard Jog' in names


@pytest.fixture(scope='module')
def loaded(tmp_path_factory):
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq.dashboard import DashBoard
    from pymodaq_plugins_keyboardjog.tools import mock_config
    app()
    data = tmp_path_factory.mktemp('kj_dash')
    cwd = os.getcwd()
    os.chdir(data)                            # the 5.1 dashboard creates its default data folder in the cwd
    orig_folder = kj.default_folder
    kj.default_folder = lambda config=None: data / 'setups'
    orig_check = getattr(DashBoard, 'check_update', None)
    DashBoard.check_update = lambda self, show=True: False          # no network in tests
    path = mock_config.write_mock_config(NAME, MOVES, overwrite=True)
    try:
        if mock_config.is_pymodaq_52():
            from pymodaq.dashboard import load_dashboard_with_experiment
            dashboard, extension, win = load_dashboard_with_experiment(NAME, kj.CLASS_NAME.upper())
        else:
            from pymodaq_gui.utils.dock import DockArea
            win = QtWidgets.QMainWindow()
            area = DockArea()
            win.setCentralWidget(area)
            dashboard = DashBoard(area)
            dashboard.set_preset_mode(path)
            extension = dashboard.load_extension_from_name('Keyboard Jog')
        # PyMoDAQ 5.3 creates and initializes the modules while the event loop runs
        assert wait(lambda: sorted(extension.ports) == sorted(t for t, _ in MOVES), 60)   # order: init order
        assert wait(lambda: all(p.is_initialized() for p in extension.ports.values()), 60)
        yield dashboard, extension
        try:
            extension.quit_fun()
            dashboard.quit_fun()
            wait(timeout=1.0)
        except Exception:
            pass
    finally:
        os.chdir(cwd)
        kj.default_folder = orig_folder
        if orig_check is not None:
            DashBoard.check_update = orig_check
        for p in path.parent.glob(f'{NAME}*'):
            try:
                p.unlink()
            except OSError:
                pass
        for folder in ('overshooter_configs', 'states'):          # created by PyMoDAQ >= 5.2 for the experiment
            shutil.rmtree(path.parent.parent / folder / NAME, ignore_errors=True)


def test_dashboard_runs_the_extension(loaded):
    dashboard, ext = loaded
    from pymodaq_plugins_keyboardjog.extensions.keyboard_jog import KeyboardJog
    from pymodaq_plugins_keyboardjog.core.model import VERTICAL, JogSetup
    assert isinstance(ext, KeyboardJog)
    win = ext.mainwindow
    assert win.windowFlags() & QtCore.Qt.WindowStaysOnTopHint
    assert not win.menuBar().isVisible()
    ext._write_tree(JogSetup(pair_numbers={'Jog X': 1, 'Jog Y': 1}, axes={'Jog Y': VERTICAL},
                             steps={'Jog X': 0.05}))
    ext.apply_settings()
    assert wait(lambda: ext.values.get('Jog X') is not None, 10)
    x0 = ext.values['Jog X']
    win.activateWindow()
    ext.panel.setFocus()
    assert wait(lambda: ext.panel.armed, 5)
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('press', QtCore.Qt.Key_D))
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('release', QtCore.Qt.Key_D))
    assert wait(lambda: abs(ext.values['Jog X'] - x0 - 0.05) < 1e-3, 15)
