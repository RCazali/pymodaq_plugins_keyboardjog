"""The extension with real DAQ_Move modules (Mock actuators of pymodaq_plugins_mock, no hardware).

Covers the checklist of the specification: focus green / red, no motion when red, step mode one press = one step,
continuous mode stops on release, focus loss while a key is held, no move queueing with a slow actuator, +/- step
changes, Shift / Ctrl in continuous mode, setup save / load / delete, setup with a missing actuator, last setup
reloaded at startup, always on top; and the per-actuator settings (pair number, keys, continuous) and the history.
"""
import pytest
from qtpy import QtCore, QtWidgets

pytest.importorskip('pymodaq')
pytest.importorskip('pymodaq_plugins_mock')

from helpers import FakeDashboard, app, key_event, make_mock_move, set_tau, wait  # noqa: E402
from pymodaq_plugins_keyboardjog.core.model import VERTICAL, ExtraKeys, JogSetup  # noqa: E402
from pymodaq_plugins_keyboardjog.ui.panel import ARMED_COLOR, DISARMED_COLOR  # noqa: E402
from pymodaq_plugins_keyboardjog.ui.settings import actuator_group, extra_groups  # noqa: E402

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
    """Records the move_rel / move_abs / stop_motion calls of a DAQ_Move (and whether it was idle at each call)"""

    def __init__(self, module, monkeypatch):
        self.module = module
        self.moves = []
        self.abs_moves = []
        self.idle_at_call = []
        self.stops = 0
        move_rel, move_abs, stop = module.move_rel, module.move_abs, module.stop_motion

        def spy_move_rel(value, *args, **kwargs):
            self.moves.append(float(value))
            self.idle_at_call.append(bool(module.move_done_bool))
            return move_rel(value, *args, **kwargs)

        def spy_move_abs(value, *args, **kwargs):
            self.abs_moves.append(float(value))
            return move_abs(value, *args, **kwargs)

        def spy_stop():
            self.stops += 1
            return stop()

        monkeypatch.setattr(module, 'move_rel', spy_move_rel)
        monkeypatch.setattr(module, 'move_abs', spy_move_abs)
        monkeypatch.setattr(module, 'stop_motion', spy_stop)


def new_extension(modules, folder, monkeypatch):
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq_gui.utils.dock import DockArea
    monkeypatch.setattr(kj, 'default_folder', lambda config=None: folder / 'setups')
    win = QtWidgets.QMainWindow()
    area = DockArea()
    win.setCentralWidget(area)
    ext = kj.KeyboardJog(area, FakeDashboard(modules))
    return ext, win


@pytest.fixture
def jog(modules, tmp_path, monkeypatch):
    for m in modules:
        set_tau(m, 50)
        assert wait(lambda: m.move_done_bool, 10)
    spies = {m.title: Spy(m, monkeypatch) for m in modules}
    ext, win = new_extension(modules, tmp_path, monkeypatch)
    win.show()
    activate(ext)
    configure(ext, JogSetup(displayed=list(NAMES), pair_numbers={'Stage X': 1, 'Stage Y': 1},
                            axes={'Stage Y': VERTICAL}, extra_keys=[ExtraKeys('Focus Z', 'PgDown', 'PgUp')],
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


def with_changes(ext, **changes):
    """The current setup with some changes"""
    return JogSetup(**{**ext.setup.__dict__, **changes})


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


def menu_action(menu, *path):
    """The action of a (sub)menu by its texts"""
    for text in path[:-1]:
        menu = next(a.menu() for a in menu.actions() if a.text() == text)
    return next(a for a in menu.actions() if a.text() == path[-1])


# ---------------------------------------------------------------------------------------------- view and focus
def test_main_view_shows_bound_actuators_with_live_values(jog):
    ext, spies = jog
    assert ext.panel.row_names() == list(NAMES)
    assert wait(lambda: all(ext.panel.value_text(n) not in ('', '---') for n in NAMES), 5)
    assert ext.panel.value_text('Stage X').endswith('mm')
    assert ext.panel.step_text('Stage Y') == 'step 0.02'
    assert [(g.label, g.actuators) for g in ext.groups] == [('1', ['Stage X', 'Stage Y']), ('2', ['Focus Z'])]
    assert ext.panel.selected_names() == ['Stage X', 'Stage Y']
    assert ext.panel.keys_text('Stage X') == 'A/D' and ext.panel.keys_text('Stage Y') == 'S/W'
    assert ext.panel.keys_text('Focus Z') == 'PgDown/PgUp'


def test_works_out_of_the_box(modules, tmp_path, monkeypatch):
    """No setup at all: every actuator is shown with a number, horizontal, the first one is selected"""
    spies = {m.title: Spy(m, monkeypatch) for m in modules}
    ext, win = new_extension(modules, tmp_path / 'fresh', monkeypatch)
    win.show()
    try:
        activate(ext)
        assert [(g.label, g.actuators) for g in ext.groups] == [('1', ['Stage X']), ('2', ['Stage Y']),
                                                                ('3', ['Focus Z'])]
        assert ext.panel.selected_names() == ['Stage X']
        assert ext.panel.keys_text('Stage X') == 'A/D'
        assert not ext.panel.history_visible()                    # history hidden by default
        ext.controller.steps = {n: 0.01 for n in NAMES}
        tap(ext, Qt.Key_D)
        idle(ext, spies)
        tap(ext, Qt.Key_W)                                        # horizontal actuator: W does nothing
        wait(timeout=0.2)
        assert spies['Stage X'].moves == [pytest.approx(0.01)]
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


def test_moving_value_is_highlighted(jog, modules):
    ext, spies = jog
    set_tau(modules[0], 800)
    tap(ext, Qt.Key_D)
    assert ext.panel.is_busy_shown('Stage X') and not ext.panel.is_busy_shown('Stage Y')
    idle(ext, spies)
    assert wait(lambda: not ext.panel.is_busy_shown('Stage X'), 2)


def test_no_queue_with_slow_actuator(jog, modules):
    ext, spies = jog
    set_tau(modules[1], 1500)
    for _ in range(5):
        tap(ext, Qt.Key_W)                              # step mode: only the first press moves
        wait(timeout=0.05)
    assert spies['Stage Y'].moves == [pytest.approx(0.02)]
    configure(ext, with_changes(ext, continuous=list(NAMES)))
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
def continuous(ext, names=NAMES):
    configure(ext, with_changes(ext, continuous=list(names)))
    assert ext.controller.continuous == set(names)


def test_continuous_mode_stops_on_release(jog):
    ext, spies = jog
    continuous(ext)
    assert ext.panel.step_text('Stage X') == 'cont. 0.01'
    press(ext, Qt.Key_D)
    assert wait(lambda: len(spies['Stage X'].moves) >= 3, 5)
    release(ext, Qt.Key_D)
    n = len(spies['Stage X'].moves)
    wait(timeout=0.6)
    assert len(spies['Stage X'].moves) == n             # no step after the release
    assert all(spies['Stage X'].idle_at_call)           # never sent while the previous move was running
    assert all(d == pytest.approx(0.01) for d in spies['Stage X'].moves)


def test_continuous_is_per_actuator(jog):
    ext, spies = jog
    continuous(ext, ['Stage Y'])
    assert ext.panel.step_text('Stage X') == 'step 0.01' and ext.panel.step_text('Stage Y') == 'cont. 0.02'
    press(ext, Qt.Key_D)
    press(ext, Qt.Key_W)
    assert wait(lambda: len(spies['Stage Y'].moves) >= 3, 5)
    release(ext, Qt.Key_D)
    release(ext, Qt.Key_W)
    idle(ext, spies)
    assert spies['Stage X'].moves == [pytest.approx(0.01)]


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
    assert ext.panel.mode_label.text() == 'step x10'
    press(ext, Qt.Key_D, Qt.ShiftModifier)
    assert wait(lambda: len(spies['Stage X'].moves) >= 2, 5)
    release(ext, Qt.Key_D, Qt.ShiftModifier)
    release(ext, Qt.Key_Shift)
    assert ext.panel.mode_label.text() == ''
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
    assert ext.panel.step_text('Stage X') == 'cont. 0.01'


# ---------------------------------------------------------------------------------------------- step size
def test_plus_minus_change_the_steps_of_the_selection(jog):
    ext, spies = jog
    tap(ext, Qt.Key_Plus)
    assert ext.controller.step('Stage X') == pytest.approx(0.1)
    assert ext.controller.step('Stage Y') == pytest.approx(0.2)
    assert ext.controller.step('Focus Z') == pytest.approx(0.005)     # not selected: unchanged
    assert ext.panel.step_text('Stage X') == 'step 0.1'
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


# ---------------------------------------------------------------------------------------------- selection and pairs
def test_selection_by_number_and_click(jog):
    ext, spies = jog
    from qtpy.QtTest import QTest
    tap(ext, Qt.Key_2)                                   # Focus Z: the movement keys move it now
    assert ext.panel.selected_names() == ['Focus Z']
    assert ext.panel.keys_text('Focus Z') == 'A/D  PgDown/PgUp'
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


def test_pair_number_and_keys_in_the_settings(jog):
    """The settings of each actuator: same pair number = one group, horizontal = A/D, vertical = S/W, 0 = number 10"""
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), steps={n: 0.01 for n in NAMES}))
    assert [(g.label, g.actuators) for g in ext.groups] == [('1', ['Stage X']), ('2', ['Stage Y']),
                                                            ('3', ['Focus Z'])]
    focus = actuator_group(ext.settings, 'Focus Z')
    focus.child('pair').setValue('0')
    focus.child('axis').setValue(VERTICAL)
    assert [g.label for g in ext.groups] == ['1', '2', '0']
    tap(ext, Qt.Key_0)
    assert ext.panel.selected_names() == ['Focus Z']
    assert ext.panel.keys_text('Focus Z') == 'S/W'
    tap(ext, Qt.Key_D)                                   # vertical: A / D do nothing
    tap(ext, Qt.Key_W)
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(0.01)]
    actuator_group(ext.settings, 'Stage X').child('pair').setValue('0')     # X joins Focus Z: a pair
    assert [g.actuators for g in ext.groups] == [['Stage Y'], ['Stage X', 'Focus Z']]
    assert ext.groups[0].label == '1' and ext.groups[1].label == '0'
    assert ext.panel.header_text(1) == 'Stage X / Focus Z'
    assert ext.panel.selected_names() == ['Stage X', 'Focus Z']
    actuator_group(ext.settings, 'Stage Y').child('pair').setValue('0')     # third one in the pair: reported
    assert ext.settings.child('problems').opts['visible']
    assert 'both horizontal' in ext.settings['problems']
    assert ext.settings['setup', 'current'].endswith('*')


def test_right_click_menu(jog):
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), steps={n: 0.01 for n in NAMES}))
    menu = ext.group_menu(0, 'Stage X')                  # right-click menu of a single actuator
    assert [a.text() for a in menu.actions()] == ["Pair 'Stage X' with", 'Pair number', 'Keys', 'Continuous']
    assert [a.text() for a in menu.actions()[0].menu().actions()] == ['Stage Y', 'Focus Z']
    pair_number = menu.actions()[1].menu()
    assert [a.text() for a in pair_number.actions() if a.isChecked()] == ['auto']
    menu_action(menu, 'Continuous').trigger()
    assert ext.controller.continuous == {'Stage X'}
    assert actuator_group(ext.settings, 'Stage X').child('continuous').value() is True
    menu = ext.group_menu(2, 'Focus Z')
    menu_action(menu, 'Keys', 'vertical (S/W)').trigger()
    assert ext.setup.axis('Focus Z') == VERTICAL
    menu = ext.group_menu(2, 'Focus Z')
    menu_action(menu, 'Pair number', '5').trigger()
    assert [g.label for g in ext.groups] == ['1', '2', '5']


def test_pairs_from_the_main_view(jog):
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), steps={n: 0.01 for n in NAMES}))
    ext.pair_actuators('Stage X', 'Focus Z', name='Sample XZ')
    assert [(g.label, g.actuators) for g in ext.groups] == [('1', ['Stage X', 'Focus Z']), ('2', ['Stage Y'])]
    assert actuator_group(ext.settings, 'Focus Z').child('pair').value() == '1'
    assert actuator_group(ext.settings, 'Focus Z').child('axis').value() == VERTICAL
    assert ext.panel.header_text(0) == 'Sample XZ'
    assert ext.panel.selected_names() == ['Stage X', 'Focus Z']
    assert ext.panel.keys_text('Stage X') == 'A/D' and ext.panel.keys_text('Focus Z') == 'S/W'
    tap(ext, Qt.Key_W)                                   # vertical actuator of the pair
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(0.01)]
    menu = ext.group_menu(0)                             # right-click menu of a pair header
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == ["Rename 'Sample XZ'…", 'Unpair']
    ext.rename_pair(0, 'Microscope')
    assert ext.panel.header_text(0) == 'Microscope'
    assert ext.settings['setup', 'current'].endswith('*')
    ext.save_setup('pairs')
    loaded = ext.store.load('pairs')
    assert loaded.pair_names == {1: 'Microscope'} and loaded.pair_numbers == {'Stage X': 1, 'Focus Z': 1}
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


# ---------------------------------------------------------------------------------------------- history
def test_history_records_and_goes_back(jog):
    ext, spies = jog
    assert not ext.history_plot.isVisible()
    ext.panel.history_button.click()                     # the graph button shows it
    assert ext.panel.history_visible() and ext.history_plot.isVisible()
    assert ext.settings['general', 'show_history'] is True
    assert ext.panel.armed                               # the button does not take the focus
    assert wait(lambda: all(ext.values.get(n) is not None for n in NAMES), 5)
    x0, y0 = ext.values['Stage X'], ext.values['Stage Y']
    tap(ext, Qt.Key_D)
    idle(ext, spies)
    tap(ext, Qt.Key_W)
    idle(ext, spies)
    points = ext.history.points(['Stage X', 'Stage Y'])
    assert len(points) == 3                              # start, after D, after W
    assert points[0][1:] == pytest.approx([x0, y0], abs=1e-3)
    assert points[-1][1:] == pytest.approx([x0 + 0.01, y0 + 0.02], abs=1e-3)
    assert ext.history_plot.point_count() == 3
    assert ext.go_back(0, confirm=False)                 # click on the first point
    idle(ext, spies)
    assert spies['Stage X'].abs_moves == [pytest.approx(x0)] and spies['Stage Y'].abs_moves == [pytest.approx(y0)]
    assert wait(lambda: abs(ext.values['Stage X'] - x0) < 1e-3, 5)
    assert wait(lambda: ext.history.path.is_file(), 5)   # saved shortly after the moves
    ext.clear_history(confirm=False)
    assert ext.history.points(['Stage X', 'Stage Y']) == [] and ext.history_plot.point_count() == 0
    ext.panel.history_button.click()
    assert not ext.history_plot.isVisible() and ext.settings['general', 'show_history'] is False


def test_history_of_a_single_actuator_moved_from_elsewhere(jog, modules):
    ext, spies = jog
    tap(ext, Qt.Key_2)
    ext.panel.show_history(True)
    assert wait(lambda: ext.values.get('Focus Z') is not None, 5)
    z0 = ext.values['Focus Z']
    modules[2].move_rel(0.5)                             # moved by the Dashboard, not by this window
    idle(ext, spies)
    assert [p[1] for p in ext.history.points(['Focus Z'])] == [pytest.approx(z0, abs=1e-3),
                                                               pytest.approx(z0 + 0.5, abs=1e-3)]
    assert ext.history_plot.point_count() == 2


# ---------------------------------------------------------------------------------------------- settings and setups
def test_key_conflicts_are_shown_and_disabled(jog):
    ext, spies = jog
    configure(ext, JogSetup(displayed=list(NAMES), extra_keys=[
        ExtraKeys('Focus Z', 'PgDown', 'PgUp'), ExtraKeys('Stage Y', 'Home', 'PgUp'),
        ExtraKeys('Stage X', 'Up', 'End')], steps={'Stage X': 0.01}))
    problems = ext.settings.child('problems')
    assert problems.opts['visible'] and 'PgUp' in problems.value() and 'reserved' in problems.value()
    tap(ext, Qt.Key_PageUp)
    wait(timeout=0.3)
    assert not spies['Stage Y'].moves and not spies['Focus Z'].moves
    tap(ext, Qt.Key_End)
    idle(ext, spies)
    assert spies['Stage X'].moves == [pytest.approx(0.01)]


def test_settings_tree_edits_apply(jog):
    ext, spies = jog
    extra = extra_groups(ext.settings)[0]
    extra.child('plus').setValue('home')
    assert extra.child('plus').value() == 'Home'          # key names are normalized
    tap(ext, Qt.Key_Home)
    idle(ext, spies)
    assert spies['Focus Z'].moves == [pytest.approx(0.005)]
    ext.settings.child('extra', 'add').activate()
    assert len(extra_groups(ext.settings)) == 2
    extra_groups(ext.settings)[1].child('remove').activate()
    assert len(extra_groups(ext.settings)) == 1
    actuator_group(ext.settings, 'Focus Z').child('continuous').setValue(True)
    assert ext.controller.continuous == {'Focus Z'}
    assert ext.settings['setup', 'current'].endswith('*')


def test_setup_save_load_delete(jog):
    ext, spies = jog
    ext.settings.child('setup', 'new_name').setValue('bench A')
    ext.settings.child('setup', 'save_as').activate()
    assert ext.store.names() == ['bench A'] and ext.setup_name == 'bench A'
    assert ext.store.last == 'bench A'
    tap(ext, Qt.Key_Plus)
    actuator_group(ext.settings, 'Stage X').child('continuous').setValue(True)
    assert ext.settings['setup', 'current'] == 'bench A *'
    ext.load_setup('bench A')
    assert ext.controller.continuous == set()
    assert ext.controller.step('Stage X') == pytest.approx(0.01)
    assert [g.actuators for g in ext.groups] == [['Stage X', 'Stage Y'], ['Focus Z']]
    assert ext.settings['setup', 'current'] == 'bench A'
    ext.delete_setup('bench A')
    assert ext.store.names() == [] and ext.store.last == ''


def test_setup_with_missing_actuator(jog):
    ext, spies = jog
    ext.store.save('old bench', JogSetup(displayed=['Ghost'], pair_numbers={'Stage X': 1, 'Ghost Y': 1},
                                         axes={'Ghost Y': VERTICAL},
                                         extra_keys=[ExtraKeys('Ghost Z', 'PgDown', 'PgUp')]))
    warnings = ext.load_setup('old bench')
    assert len(warnings) == 3
    assert ext.panel.row_names() == ['Stage X']
    assert 'warnings' in ext.panel.message_label.text()
    tap(ext, Qt.Key_PageUp)                              # the skipped binding does nothing
    tap(ext, Qt.Key_D)
    idle(ext, spies)
    assert spies['Stage X'].moves and not spies['Focus Z'].moves


def test_last_setup_reloaded_at_startup(jog, modules, tmp_path, monkeypatch):
    ext, spies = jog
    actuator_group(ext.settings, 'Focus Z').child('continuous').setValue(True)
    ext.panel.show_history(True)
    ext.save_setup('daily')
    other, win = new_extension(modules, tmp_path, monkeypatch)
    try:
        assert other.setup_name == 'daily'
        assert other.controller.continuous == {'Focus Z'}
        assert other.panel.row_names() == list(NAMES)
        assert other.panel.history_visible()
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
    ext.panel.show_history(True)
    wait(timeout=0.2)
    assert ext.mainwindow.height() >= 350
    ext.panel.show_history(False)
    wait(timeout=0.2)
    assert ext.mainwindow.height() < 250
