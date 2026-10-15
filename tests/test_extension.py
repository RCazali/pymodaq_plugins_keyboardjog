"""The extension with real DAQ_Move modules (Mock actuators of pymodaq_plugins_mock, no hardware).

Covers the checklist of the specification: focus green / red, no motion when red, step mode one press = one step,
continuous mode stops on release, focus loss while a key is held, no move queueing with a slow actuator, +/- step
changes, Shift / Ctrl in continuous mode, setup save / load / delete, setup with a missing actuator, last setup
reloaded at startup, always on top.
"""
import pytest
from qtpy import QtCore, QtWidgets

pytest.importorskip('pymodaq')
pytest.importorskip('pymodaq_plugins_mock')

from helpers import FakeDashboard, app, key_event, make_mock_move, set_tau, wait  # noqa: E402
from pymodaq_plugins_keyboardjog.core.model import Binding, JogSetup  # noqa: E402
from pymodaq_plugins_keyboardjog.ui.panel import ARMED_COLOR, DISARMED_COLOR  # noqa: E402

pytestmark = pytest.mark.pymodaq
Qt = QtCore.Qt
NAMES = ('Stage X', 'Stage Y', 'Focus Z')


@pytest.fixture(autouse=True)
def qwerty_labels(monkeypatch):
    """The WASD keys are matched by position; only their labels depend on the layout: fix them for the tests"""
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    monkeypatch.setattr(kj, 'is_azerty', lambda: False)


@pytest.fixture(scope='module')
def modules():
    app()
    mods = [make_mock_move(name, axis='Y', tau_ms=50) for name in NAMES]
    yield mods
    for m in mods:
        m.quit_fun()
    wait(timeout=0.5)


class Spy:
    """Records the move_rel / stop_motion calls of a DAQ_Move (and whether it was idle at each call)"""

    def __init__(self, module, monkeypatch):
        self.module = module
        self.moves = []
        self.idle_at_call = []
        self.stops = 0
        move_rel, stop = module.move_rel, module.stop_motion

        def spy_move_rel(value, *args, **kwargs):
            self.moves.append(float(value))
            self.idle_at_call.append(bool(module.move_done_bool))
            return move_rel(value, *args, **kwargs)

        def spy_stop():
            self.stops += 1
            return stop()

        monkeypatch.setattr(module, 'move_rel', spy_move_rel)
        monkeypatch.setattr(module, 'stop_motion', spy_stop)


@pytest.fixture
def jog(modules, tmp_path, monkeypatch):
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq_gui.utils.dock import DockArea
    monkeypatch.setattr(kj, 'default_folder', lambda config=None: tmp_path / 'setups')
    for m in modules:
        set_tau(m, 50)
        assert wait(lambda: m.move_done_bool, 10)
    spies = {m.title: Spy(m, monkeypatch) for m in modules}
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    ext = kj.KeyboardJog(area, FakeDashboard(modules))
    win.show()
    activate(ext)
    configure(ext, JogSetup(displayed=list(NAMES),
                            bindings=[Binding.pair('Stage X', 'Stage Y'), Binding.single('Focus Z', 'PgDown', 'PgUp')],
                            steps={'Stage X': 0.01, 'Stage Y': 0.02, 'Focus Z': 0.005}))
    yield ext, spies
    ext.quit_fun()
    win.close()
    for m in modules:
        m.stop_motion()
    wait(timeout=0.3)


def configure(ext, setup):
    ext._write_tree(setup)
    ext.apply_settings()


def activate(ext):
    ext.mainwindow.activateWindow()
    ext.panel.setFocus(Qt.OtherFocusReason)
    assert wait(lambda: ext.panel.armed, 5), 'the window could not be activated'


def deactivate(ext):
    other = QtWidgets.QLineEdit()
    other.show()
    other.activateWindow()
    other.setFocus()
    assert wait(lambda: not ext.panel.armed, 5)
    return other


def press(ext, key, modifiers=None, auto_repeat=False):
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('press', key, modifiers, auto_repeat))


def release(ext, key, modifiers=None, auto_repeat=False):
    QtWidgets.QApplication.sendEvent(ext.panel, key_event('release', key, modifiers, auto_repeat))


def tap(ext, key, modifiers=None):
    press(ext, key, modifiers)
    release(ext, key, modifiers)


def idle(ext, spies, timeout=10):
    assert wait(lambda: all(s.module.move_done_bool for s in spies.values()) and
                not any(ext.controller.is_busy(n) for n in NAMES), timeout)


# ---------------------------------------------------------------------------------------------- view and focus
def test_main_view_shows_bound_actuators_with_live_values(jog):
    ext, spies = jog
    assert ext.panel.row_names() == list(NAMES)
    assert wait(lambda: all(ext.panel.value_text(n) not in ('', '---') for n in NAMES), 5)
    assert ext.panel.value_text('Stage X').endswith('mm')
    assert ext.panel.step_text('Stage Y') == 'step 0.02'
    assert [g.actuators for g in ext.groups] == [['Stage X', 'Stage Y'], ['Focus Z']]
    assert ext.panel.selected_names() == ['Stage X', 'Stage Y']
    assert ext.panel.keys_text('Stage X') == 'A/D' and ext.panel.keys_text('Stage Y') == 'S/W'
    assert ext.panel.keys_text('Focus Z') == 'PgDown/PgUp'


def test_works_out_of_the_box(modules, tmp_path, monkeypatch):
    """No setup at all: every actuator is shown with a number, the first one is selected, the arrows move it"""
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq_gui.utils.dock import DockArea
    monkeypatch.setattr(kj, 'default_folder', lambda config=None: tmp_path / 'fresh')
    spies = {m.title: Spy(m, monkeypatch) for m in modules}
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    ext = kj.KeyboardJog(area, FakeDashboard(modules))
    win.show()
    try:
        activate(ext)
        assert [g.actuators for g in ext.groups] == [[n] for n in NAMES]
        assert ext.panel.selected_names() == ['Stage X']
        assert ext.panel.keys_text('Stage X') == 'A/D S/W'
        ext.controller.steps = {n: 0.01 for n in NAMES}
        tap(ext, Qt.Key_D)
        idle(ext, spies)
        tap(ext, Qt.Key_W)
        idle(ext, spies)
        assert spies['Stage X'].moves == [pytest.approx(0.01), pytest.approx(0.01)]
        tap(ext, Qt.Key_2)
        tap(ext, Qt.Key_A)
        idle(ext, spies)
        assert spies['Stage Y'].moves == [pytest.approx(-0.01)]
        assert ext.panel.selected_names() == ['Stage Y']
    finally:
        ext.quit_fun()
        win.close()


def test_focus_indicator_green_red(jog):
    ext, spies = jog
    assert ext.panel.armed and ARMED_COLOR in ext.panel.styleSheet()
    other = deactivate(ext)
    assert DISARMED_COLOR in ext.panel.styleSheet()
    activate(ext)
    assert ARMED_COLOR in ext.panel.styleSheet()
    ext.panel.show_settings(True)                      # typing in the settings must never move anything
    ext.tree.setFocus()
    assert wait(lambda: not ext.panel.armed, 5)
    ext.panel.show_settings(False)
    assert wait(lambda: ext.panel.armed, 5)
    other.close()


def test_no_motion_when_red(jog):
    ext, spies = jog
    other = deactivate(ext)
    tap(ext, Qt.Key_D)                               # even delivered to the panel, ignored
    tap(ext, Qt.Key_PageUp)
    wait(timeout=0.3)
    assert all(not s.moves for s in spies.values())
    other.close()


# ---------------------------------------------------------------------------------------------- step mode
def test_step_mode_one_press_one_step(jog):
    ext, spies = jog
    x0 = ext.values['Stage X']
    press(ext, Qt.Key_D)
    for _ in range(10):                                  # OS auto-repeat while held: ignored
        release(ext, Qt.Key_D, auto_repeat=True)
        press(ext, Qt.Key_D, auto_repeat=True)
    wait(timeout=0.5)
    release(ext, Qt.Key_D)
    assert spies['Stage X'].moves == [pytest.approx(0.01)]
    idle(ext, spies)
    assert wait(lambda: abs(ext.values['Stage X'] - x0 - 0.01) < 1e-3, 5)
    tap(ext, Qt.Key_S)
    tap(ext, Qt.Key_PageUp)
    idle(ext, spies)
    assert spies['Stage Y'].moves == [pytest.approx(-0.02)]
    assert spies['Focus Z'].moves == [pytest.approx(0.005)]


def test_no_queue_with_slow_actuator(jog, modules):
    ext, spies = jog
    set_tau(modules[1], 1500)
    for _ in range(5):
        tap(ext, Qt.Key_W)                              # step mode: only the first press moves
        wait(timeout=0.05)
    assert spies['Stage Y'].moves == [pytest.approx(0.02)]
    configure(ext, ext.setup.__class__(**{**ext.setup.__dict__, 'motion_mode': 'continuous'}))
    idle(ext, spies, 15)
    spies['Stage Y'].moves.clear()
    press(ext, Qt.Key_W)                                # continuous: next step only after move done
    wait(timeout=0.8)
    assert len(spies['Stage Y'].moves) == 1
    release(ext, Qt.Key_W)
    idle(ext, spies, 15)
    assert len(spies['Stage Y'].moves) == 1
    assert all(spies['Stage Y'].idle_at_call)


# ---------------------------------------------------------------------------------------------- continuous mode
def continuous(ext):
    configure(ext, ext.setup.__class__(**{**ext.setup.__dict__, 'motion_mode': 'continuous'}))
    assert ext.controller.mode == 'continuous'


def test_continuous_mode_stops_on_release(jog):
    ext, spies = jog
    continuous(ext)
    press(ext, Qt.Key_D)
    assert wait(lambda: len(spies['Stage X'].moves) >= 3, 5)
    release(ext, Qt.Key_D)
    n = len(spies['Stage X'].moves)
    wait(timeout=0.6)
    assert len(spies['Stage X'].moves) == n             # no step after the release
    assert all(spies['Stage X'].idle_at_call)           # never sent while the previous move was running
    assert all(d == pytest.approx(0.01) for d in spies['Stage X'].moves)


def test_focus_loss_during_held_key(jog):
    ext, spies = jog
    continuous(ext)
    press(ext, Qt.Key_A)
    assert wait(lambda: len(spies['Stage X'].moves) >= 2, 5)
    other = deactivate(ext)
    n = len(spies['Stage X'].moves)
    assert not ext.controller.is_held('Stage X')
    wait(timeout=0.6)
    assert len(spies['Stage X'].moves) <= n + 1 and spies['Stage X'].moves[-1] < 0
    n = len(spies['Stage X'].moves)
    activate(ext)                                       # the key is not considered held anymore
    wait(timeout=0.5)
    assert len(spies['Stage X'].moves) == n
    release(ext, Qt.Key_A)
    other.close()


def test_shift_and_ctrl_in_continuous_mode(jog):
    ext, spies = jog
    continuous(ext)
    press(ext, Qt.Key_Shift, Qt.ShiftModifier)
    press(ext, Qt.Key_D, Qt.ShiftModifier)
    assert wait(lambda: len(spies['Stage X'].moves) >= 2, 5)
    release(ext, Qt.Key_D, Qt.ShiftModifier)
    release(ext, Qt.Key_Shift)
    idle(ext, spies)
    assert all(d == pytest.approx(0.1) for d in spies['Stage X'].moves)
    spies['Stage X'].moves.clear()
    press(ext, Qt.Key_Control, Qt.ControlModifier)
    press(ext, Qt.Key_D, Qt.ControlModifier)
    assert wait(lambda: len(spies['Stage X'].moves) >= 2, 5)
    release(ext, Qt.Key_D, Qt.ControlModifier)
    release(ext, Qt.Key_Control)
    idle(ext, spies)
    assert all(d == pytest.approx(0.001) for d in spies['Stage X'].moves)
    assert ext.controller.step('Stage X') == pytest.approx(0.01)   # stored step unchanged
    assert ext.panel.step_text('Stage X') == 'step 0.01'


# ---------------------------------------------------------------------------------------------- step size
def test_plus_minus_change_the_steps_of_the_selection(jog):
    ext, spies = jog
    tap(ext, Qt.Key_Plus)
    assert ext.controller.step('Stage X') == pytest.approx(0.1)
    assert ext.controller.step('Stage Y') == pytest.approx(0.2)
    assert ext.controller.step('Focus Z') == pytest.approx(0.005)     # not selected: unchanged
    assert ext.panel.step_text('Stage X') == 'step 0.1'
    from pymodaq_plugins_keyboardjog.ui.settings import actuator_group
    assert actuator_group(ext.settings, 'Stage X').child('step').value() == pytest.approx(0.1)
    tap(ext, Qt.Key_Minus)
    tap(ext, Qt.Key_Minus)
    assert ext.controller.step('Stage Y') == pytest.approx(0.002)
    tap(ext, Qt.Key_2)
    tap(ext, Qt.Key_Plus)
    assert ext.controller.step('Focus Z') == pytest.approx(0.05)
    tap(ext, Qt.Key_1)
    tap(ext, Qt.Key_D)
    idle(ext, spies)
    assert spies['Stage X'].moves == [pytest.approx(0.001)]
    ext.settings.child('general', 'step_factor').setValue(2.0)       # custom factor
    tap(ext, Qt.Key_Plus)
    assert ext.controller.step('Stage X') == pytest.approx(0.002)


def test_selection_by_number_and_click(jog):
    ext, spies = jog
    from qtpy.QtTest import QTest
    tap(ext, Qt.Key_2)                                   # Focus Z: the arrows move it now
    assert ext.panel.selected_names() == ['Focus Z']
    assert ext.panel.keys_text('Focus Z') == 'A/D S/W  PgDown/PgUp'
    assert ext.panel.keys_text('Stage X') == ''
    tap(ext, Qt.Key_A)
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(-0.005)] and not spies['Stage X'].moves
    tap(ext, Qt.Key_7)                                   # no group 7: nothing changes
    assert ext.panel.selected_names() == ['Focus Z']
    assert '7' in ext.panel.message_label.text()
    QTest.mouseClick(ext.panel._rows['Stage Y'].name, Qt.LeftButton)   # a click selects the pair
    assert ext.panel.selected_names() == ['Stage X', 'Stage Y']
    assert ext.panel.armed
    tap(ext, Qt.Key_S)
    idle(ext, spies)
    assert spies['Stage Y'].moves == [pytest.approx(-0.02)]


def test_pairs_from_the_main_view(jog):
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), steps={n: 0.01 for n in NAMES}))
    assert [g.actuators for g in ext.groups] == [['Stage X'], ['Stage Y'], ['Focus Z']]
    menu = ext.group_menu(0, 'Stage X')                  # right-click menu of a single actuator
    sub = menu.actions()[0].menu()
    assert [a.text() for a in sub.actions()] == ['Stage Y', 'Focus Z']
    ext.pair_actuators('Stage X', 'Focus Z', name='Sample XZ')
    assert [g.actuators for g in ext.groups] == [['Stage X', 'Focus Z'], ['Stage Y']]
    assert ext.panel.header_text(0) == 'Sample XZ'
    assert ext.panel.selected_names() == ['Stage X', 'Focus Z']
    assert ext.panel.keys_text('Stage X') == 'A/D' and ext.panel.keys_text('Focus Z') == 'S/W'
    tap(ext, Qt.Key_W)                                   # second actuator of the pair
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(0.01)]
    menu = ext.group_menu(0)                             # right-click menu of a pair
    assert [a.text() for a in menu.actions()] == ["Rename 'Sample XZ'…", 'Unpair']
    ext.rename_pair(0, 'Microscope')
    assert ext.panel.header_text(0) == 'Microscope'
    assert ext.settings['setup', 'current'].endswith('*')
    ext.save_setup('pairs')
    assert ext.store.load('pairs').pairs[0].name == 'Microscope'
    ext.unpair(0)
    assert [g.actuators for g in ext.groups] == [['Stage X'], ['Stage Y'], ['Focus Z']]


def test_move_keys_setting(jog):
    ext, spies = jog
    ext.settings.child('general', 'move_keys').setValue('arrows')
    tap(ext, Qt.Key_D)                                   # WASD off
    wait(timeout=0.3)
    assert not spies['Stage X'].moves
    assert ext.panel.keys_text('Stage X') == '←/→'
    tap(ext, Qt.Key_Right)
    idle(ext, spies)
    ext.settings.child('general', 'move_keys').setValue('both')
    tap(ext, Qt.Key_D)
    idle(ext, spies)
    assert spies['Stage X'].moves == [pytest.approx(0.01)] * 2


# ---------------------------------------------------------------------------------------------- settings and setups
def test_key_conflicts_are_shown_and_disabled(jog):
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), bindings=[
        Binding.single('Focus Z', 'PgDown', 'PgUp'), Binding.single('Stage Y', 'Home', 'PgUp'),
        Binding.single('Stage X', 'Up', 'End')], steps={'Stage X': 0.01}))
    problems = ext.settings.child('bindings', 'problems')
    assert problems.opts['visible'] and 'PgUp' in problems.value() and 'reserved' in problems.value()
    tap(ext, Qt.Key_PageUp)
    wait(timeout=0.3)
    assert not spies['Stage Y'].moves and not spies['Focus Z'].moves
    tap(ext, Qt.Key_End)
    idle(ext, spies)
    assert spies['Stage X'].moves == [pytest.approx(0.01)]


def test_settings_tree_edits_apply(jog):
    ext, spies = jog
    from pymodaq_plugins_keyboardjog.ui.settings import binding_groups
    single = binding_groups(ext.settings)[1]
    single.child('plus0').setValue('home')
    assert single.child('plus0').value() == 'Home'        # key names are normalized
    tap(ext, Qt.Key_Home)
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(0.005)]
    ext.settings.child('bindings', 'add_single').activate()
    assert len(binding_groups(ext.settings)) == 3
    binding_groups(ext.settings)[2].child('remove').activate()
    assert len(binding_groups(ext.settings)) == 2
    assert ext.settings['setup', 'current'].endswith('*')


def test_setup_save_load_delete(jog):
    ext, spies = jog
    ext.settings.child('setup', 'new_name').setValue('bench A')
    ext.settings.child('setup', 'save_as').activate()
    assert ext.store.names() == ['bench A'] and ext.setup_name == 'bench A'
    assert ext.store.last == 'bench A'
    tap(ext, Qt.Key_Plus)
    ext.settings.child('general', 'motion_mode').setValue('continuous')
    assert ext.settings['setup', 'current'] == 'bench A *'
    ext.load_setup('bench A')
    assert ext.controller.mode == 'step'
    assert ext.controller.step('Stage X') == pytest.approx(0.01)
    assert ext.settings['setup', 'current'] == 'bench A'
    ext.delete_setup('bench A')
    assert ext.store.names() == [] and ext.store.last == ''


def test_setup_with_missing_actuator(jog):
    ext, spies = jog
    ext.store.save('old bench', JogSetup(displayed=['Ghost'],
                                         bindings=[Binding.pair('Stage X', 'Ghost Y'),
                                                   Binding.single('Ghost Z', 'PgDown', 'PgUp')]))
    warnings = ext.load_setup('old bench')
    assert len(warnings) == 3
    assert ext.panel.row_names() == ['Stage X']
    assert 'warnings' in ext.panel.message_label.text()
    tap(ext, Qt.Key_PageUp)                              # the skipped binding does nothing
    tap(ext, Qt.Key_D)
    idle(ext, spies)
    assert spies['Stage X'].moves and not spies['Focus Z'].moves


def test_last_setup_reloaded_at_startup(jog, modules):
    ext, spies = jog
    ext.settings.child('general', 'motion_mode').setValue('continuous')
    ext.save_setup('daily')
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq_gui.utils.dock import DockArea
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    other = kj.KeyboardJog(area, FakeDashboard(modules))
    try:
        assert other.setup_name == 'daily'
        assert other.controller.mode == 'continuous'
        assert other.panel.row_names() == list(NAMES)
    finally:
        other.quit_fun()
        win.close()


def test_always_on_top(jog):
    ext, spies = jog
    win = ext.mainwindow
    assert win.windowFlags() & Qt.WindowStaysOnTopHint
    ext.panel.on_top_check.setChecked(False)
    assert not win.windowFlags() & Qt.WindowStaysOnTopHint
    assert win.isVisible()
    assert ext.settings['general', 'always_on_top'] is False
    ext.panel.on_top_check.setChecked(True)
    assert win.windowFlags() & Qt.WindowStaysOnTopHint and win.isVisible()


def test_window_is_compact(jog):
    ext, spies = jog
    wait(timeout=0.2)
    assert ext.mainwindow.height() < 250 and ext.mainwindow.width() < 500
    ext.panel.show_settings(True)
    wait(timeout=0.2)
    assert ext.mainwindow.height() >= 500
    ext.panel.show_settings(False)
    wait(timeout=0.2)
    assert ext.mainwindow.height() < 250
