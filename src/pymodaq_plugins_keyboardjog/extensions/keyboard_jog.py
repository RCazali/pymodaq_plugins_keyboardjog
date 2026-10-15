# -*- coding: utf-8 -*-
"""
Keyboard Jog - PyMoDAQ Dashboard extension: a tiny, always-on-top window to move the Dashboard actuators with
the keyboard while showing their position. Works without any configuration:

* Green border: the window has the keyboard focus, the keys move the actuators.
  Red border: the focus is elsewhere, every key is ignored (and the actuators it was moving are stopped).
* Every actuator has a number: keys 1..9 (or a click on its row) select it, the movement keys (W A S D by their
  position, or the arrows) move the selection. Two actuators can be paired with a right-click on a row (one number
  and a name: A/D move the first, S/W the second), and an actuator can get extra keys of its own (e.g. PgDown /
  PgUp) in the settings, active whatever the selection.
* Step mode (default): one key press = one relative step. Continuous mode: steps repeated while the key is held,
  each one after the previous move is done (never queued); Shift = step x10, Ctrl = step /10 while held.
* ``+`` / ``-``: multiply / divide the step of the selection by the step factor (10 by default).
* Setups (displayed actuators, pairs, extra keys, steps, options) are saved / loaded by name from the settings.

All the motion goes through the DAQ_Move modules of the Dashboard (``move_rel``, ``stop_motion``, their signals),
see ``core/ports.py``.

Compatibility: PyMoDAQ 5.1.x (tested on 5.1.10, PyQt5) and 5.3.x (tested on 5.3.4, PyQt6).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from qtpy import QtCore, QtWidgets

from pymodaq_gui import utils as gutils
from pymodaq_utils.logger import set_logger, get_module_name

from pymodaq.extensions.utils import CustomExt  # still valid in 5.3 (pymodaq.utils.custom_ext there)

from pymodaq_plugins_keyboardjog.utils import Config as PluginConfig
from pymodaq_plugins_keyboardjog.core.controller import MotionController
from pymodaq_plugins_keyboardjog.core.input import KeyboardInput
from pymodaq_plugins_keyboardjog.core.keys import (DOWN, LEFT, RIGHT, UP, is_azerty, key_label, key_name,
                                                    movement_labels, movement_reserved_keys, normalize_key_name)
from pymodaq_plugins_keyboardjog.core.model import (CONTINUOUS_MODE, Binding, Group, JogSetup, build_groups,
                                                     build_keymap, direction_map)
from pymodaq_plugins_keyboardjog.core.ports import ActuatorPort, actuator_modules, make_ports
from pymodaq_plugins_keyboardjog.core.setups import SetupStore, clean_name, default_folder
from pymodaq_plugins_keyboardjog.ui import settings as ui_settings
from pymodaq_plugins_keyboardjog.ui.panel import JogPanel, RowInfo

logger = set_logger(get_module_name(__file__))
plugin_config = PluginConfig()

EXTENSION_NAME = 'Keyboard Jog'
CLASS_NAME = 'KeyboardJog'

Qt = QtCore.Qt

HELP = ('Click this window: green border = the keys move the actuators, red = keys ignored.\n'
        '1-9 or a click on a row: select an actuator (or a pair). W A S D (or the arrows, see the settings): move\n'
        'the selection (pair: A/D the first actuator, S/W the second one). Right-click a row: pair / rename / unpair.\n'
        '+ / - : multiply / divide the step of the selection. Continuous mode: Shift = step x10, Ctrl = step /10.\n'
        'Settings: pairs, extra keys, steps, displayed actuators, setups.')

COMPACT_SIZE = QtCore.QSize(330, 120)
SETTINGS_SIZE = QtCore.QSize(420, 640)


class KeyboardJog(CustomExt):
    """Move the Dashboard actuators with the keyboard from a tiny always-on-top window"""

    params = ui_settings.settings_params()
    # class level: PyMoDAQ 5.3 may call do_things_after_experiment_set from CustomExt.__init__
    panel: Optional[JogPanel] = None

    def __init__(self, parent: gutils.DockArea, dashboard):
        self._loading = True
        self._closing = False
        super().__init__(parent, dashboard)
        self.store = SetupStore(default_folder(plugin_config))
        self.keyboard = KeyboardInput(self)
        self.controller = MotionController(parent=self)
        self.controller.connect_source(self.keyboard)
        self.ports: Dict[str, ActuatorPort] = {}
        self.values: Dict[str, Optional[float]] = {}
        self.setup = JogSetup()
        self.setup_name = ''
        self.groups: List[Group] = []
        self.selected = 0                       # index of the selected group
        self._extra_keys: Dict[str, List[str]] = {}
        self._azerty = is_azerty()              # labels of the WASD keys only (they are matched by position)
        self._labels = movement_labels(self.setup.move_keys, self._azerty)
        self._dirty = False
        self._auto_display = True               # no setup yet: every actuator is displayed
        self.panel = JogPanel(self.keyboard)
        self.panel.setToolTip(HELP)
        self._message_timer = QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(lambda: self.panel.show_message(''))

        self.setup_ui()

        self._loading = False
        self.refresh_actuators(force=True)
        self._load_startup_setup()
        self._refresh_saved_list()

        self._modules_timer = QtCore.QTimer(self)
        self._modules_timer.setInterval(1000)
        self._modules_timer.timeout.connect(self._check_actuators)
        self._modules_timer.start()

        if self.mainwindow is not None:
            self.mainwindow.installEventFilter(self)
            self._decorate_window()
            QtCore.QTimer.singleShot(0, self._decorate_window)   # the Dashboard adds its toolbars afterwards

    # ---------------------------------------------------------------- CustomApp API (5.1 and 5.3)
    def setup_docks_and_widgets(self):
        self.docks['jog'] = gutils.Dock('Keyboard Jog', hideTitle=True)
        self.dockarea.addDock(self.docks['jog'])
        self.docks['jog'].addWidget(self.panel)
        self.tree.setMinimumHeight(320)
        self.panel.set_settings_widget(self.tree)

    def setup_docks(self):        # PyMoDAQ 5.1 calls setup_docks from setup_ui
        self.setup_docks_and_widgets()

    def setup_menus_and_toolbars(self, menubar=None):
        # PyMoDAQ 5.3: the Dashboard checks the 'show_dashboard' action of the extensions it opens
        create = getattr(self, 'create_dashboard_toolbar', None)
        if create is not None and getattr(self.dashboard, 'experiment_manager', None) is not None:
            try:
                create(add_dashboard=True, add_experiment=False, add_state=False, add_break=False)
            except Exception as e:  # pragma: no cover - never block the extension for a toolbar
                logger.warning(f'dashboard toolbar not created: {e}')

    def setup_menu(self, menubar=None):
        pass

    def setup_actions(self):
        pass  # no toolbar: everything is in the compact panel and its settings

    @property
    def _size_hint(self) -> QtCore.QSize:       # PyMoDAQ 5.3 resizes the window to it after setup_ui
        return COMPACT_SIZE

    def connect_things(self):
        self.panel.armed_changed.connect(self._on_armed_changed)
        self.panel.settings_toggled.connect(self._on_settings_toggled)
        self.panel.always_on_top_toggled.connect(self._on_top_checkbox)
        self.keyboard.step_scale_requested.connect(self.scale_steps)
        self.keyboard.select_requested.connect(lambda number: self.select_group(number - 1))
        self.panel.group_clicked.connect(self.select_group)
        self.panel.context_requested.connect(self._show_group_menu)
        self.controller.step_changed.connect(self._on_step_changed)
        self.controller.message.connect(lambda text: self.show_message(text, warning=True))
        actions = {('setup', 'load'): self._load_selected, ('setup', 'save'): self.save_setup,
                   ('setup', 'save_as'): self._save_as, ('setup', 'delete'): self._delete_selected,
                   ('bindings', 'add_pair'): self._add_pair, ('bindings', 'add_single'): self._add_single}
        for path, slot in actions.items():
            self.settings.child(*path).sigActivated.connect(lambda *_, s=slot: s())

    def value_changed(self, param):
        if self._loading or self.panel is None:
            return
        path = self.settings.childPath(param) or []
        if not path or path[0] == 'setup':
            return
        if path[0] == 'actuators' and param.name() == 'display':
            self._auto_display = False
        if path[0] == 'bindings' and param.name().startswith(('minus', 'plus')):
            normalized = normalize_key_name(param.value())
            if normalized != param.value():
                self._loading = True
                param.setValue(normalized)
                self._loading = False
        self.apply_settings()
        self._set_dirty(True)

    def child_added(self, param, data):
        pass

    def param_deleted(self, param):
        pass

    # ---------------------------------------------------------------- actuators
    def _check_actuators(self):
        """Follow the modules of the Dashboard (PyMoDAQ 5.3 creates them while the event loop runs)"""
        if self._closing:
            return
        dashboard_manager = getattr(self.dashboard, 'modules_manager', None)
        if dashboard_manager is not None and self.modules_manager is not None \
                and dashboard_manager is not self.modules_manager:
            wanted = list(getattr(dashboard_manager, 'actuators_all', []) or [])
            if [id(m) for m in wanted] != [id(m) for m in actuator_modules(self.modules_manager)]:
                try:
                    self.modules_manager.actuators_all = wanted
                except Exception as e:  # pragma: no cover
                    logger.debug(f'modules manager not updated: {e}')
        self.refresh_actuators()

    def refresh_actuators(self, force: bool = False):
        modules = actuator_modules(self.modules_manager)
        current = [getattr(p, 'module', None) for p in self.ports.values()]
        if not force and [id(m) for m in modules] == [id(m) for m in current]:
            return
        setup = ui_settings.read_setup(self.settings) if not force else self.setup
        for port in self.ports.values():
            port.disconnect()
        self.ports = make_ports(modules)
        self.values = {name: self.values.get(name) for name in self.ports}
        for name, port in self.ports.items():
            port.on_value = lambda value, n=name: self._on_value(n, value)
        self.controller.set_ports(self.ports)
        if self._auto_display:
            setup.displayed = list(self.ports)
        restricted, _ = setup.restricted_to(list(self.ports))
        self._write_tree(restricted)
        self.apply_settings()
        for port in self.ports.values():
            try:
                port.request_value()
            except Exception as e:  # pragma: no cover
                logger.debug(f'{port.name}: value not requested: {e}')

    def units(self) -> Dict[str, str]:
        return {name: port.units() for name, port in self.ports.items()}

    def _on_value(self, name: str, value: Optional[float]):
        if value is None:
            return
        self.values[name] = value
        self.panel.set_value(name, value)

    # ---------------------------------------------------------------- settings -> controller / view
    def _write_tree(self, setup: JogSetup):
        self._loading = True
        try:
            ui_settings.write_setup(self.settings, setup, list(self.ports), self.units(), self._remove_binding)
        finally:
            self._loading = False

    def apply_settings(self):
        """Read the settings tree and apply it: controller, key map, main view, window"""
        setup = ui_settings.read_setup(self.settings)
        self.setup = setup
        self.controller.mode = setup.motion_mode
        self.controller.min_interval_s = setup.min_interval_ms / 1000
        self.controller.move_timeout_s = setup.move_timeout_s
        for name in self.ports:
            self.controller.steps[name] = setup.step(name)
        keymap, problems = build_keymap(setup, movement_reserved_keys(setup.move_keys, self._azerty))
        self.keyboard.set_keymap(keymap)
        selected_before = self.selected_group()
        self.groups, group_problems = build_groups(setup, list(self.ports))
        problems = group_problems + problems
        self._loading = True
        try:
            ui_settings.set_problems(self.settings, problems)
        finally:
            self._loading = False

        self._extra_keys: Dict[str, List[str]] = {}
        for key, action in keymap.items():
            self._extra_keys.setdefault(action.actuator, ['', ''])[0 if action.direction < 0 else 1] = \
                key_label(key_name(key))
        units = self.units()
        rows = []
        for index, group in enumerate(self.groups):
            number = str(index + 1) if index < 9 else ''
            if group.is_pair:
                rows.append(RowInfo(group.name, index, number=number))
                rows += [RowInfo(name, index, units.get(name, ''), actuator=name, indent=True)
                         for name in group.actuators]
            else:
                name = group.actuators[0]
                rows.append(RowInfo(name, index, units.get(name, ''), number, actuator=name))
        self.panel.set_rows(rows)
        for row in rows:
            if not row.is_header:
                self.panel.set_value(row.actuator, self.values.get(row.actuator))
                self.panel.set_step(row.actuator, self.controller.step(row.actuator))
        self.panel.set_mode_text('continuous' if setup.motion_mode == CONTINUOUS_MODE else 'step')
        self._labels = movement_labels(setup.move_keys, self._azerty)
        self.panel.set_hint(' '.join(self._labels[d] for d in (UP, LEFT, DOWN, RIGHT)))
        self.selected = next((i for i, g in enumerate(self.groups)
                              if selected_before and g.actuators[0] in selected_before), 0)
        self._apply_selection()
        self.panel.on_top_check.blockSignals(True)
        self.panel.on_top_check.setChecked(setup.always_on_top)
        self.panel.on_top_check.blockSignals(False)
        self.apply_always_on_top(setup.always_on_top)
        if problems:
            self.show_message('Problems in the pairs / extra keys: see the settings', warning=True)

    # ---------------------------------------------------------------- selection
    def selected_group(self) -> List[str]:
        """Actuators of the selected group"""
        if 0 <= self.selected < len(self.groups):
            return list(self.groups[self.selected].actuators)
        return []

    def select_group(self, index: int):
        """Select the group of this index (0 = number 1): the movement keys and +/- act on it"""
        if not 0 <= index < len(self.groups):
            self.show_message(f'No actuator number {index + 1}')
            return
        if index != self.selected:
            self.selected = index
            self._apply_selection()

    def select_actuator(self, name: str):
        for index, group in enumerate(self.groups):
            if name in group:
                self.select_group(index)
                return

    def _apply_selection(self):
        group = self.groups[self.selected] if 0 <= self.selected < len(self.groups) else None
        self.keyboard.set_direction_map(direction_map(group, self.selected), self.setup.move_keys)
        self.panel.set_selected(self.selected)
        k = self._labels
        for g in self.groups:
            for j, name in enumerate(g.actuators):
                parts = []
                if g is group:
                    if not g.is_pair:
                        parts.append(f'{k[LEFT]}/{k[RIGHT]} {k[DOWN]}/{k[UP]}')
                    else:
                        parts.append(f'{k[LEFT]}/{k[RIGHT]}' if j == 0 else f'{k[DOWN]}/{k[UP]}')
                if name in self._extra_keys:
                    parts.append('/'.join(x or '–' for x in self._extra_keys[name]))
                self.panel.set_keys(name, '  '.join(parts))

    # ---------------------------------------------------------------- pairs from the main view
    def _show_group_menu(self, index: int, actuator: str, global_pos: QtCore.QPoint):
        menu = self.group_menu(index, actuator)
        if menu is not None and not menu.isEmpty():
            menu.exec(global_pos) if hasattr(menu, 'exec') else menu.exec_(global_pos)

    def group_menu(self, index: int, actuator: str = '') -> Optional[QtWidgets.QMenu]:
        """Right-click menu of a row: pair a single actuator with another one, rename / unpair a pair"""
        if not 0 <= index < len(self.groups):
            return None
        group = self.groups[index]
        menu = QtWidgets.QMenu(self.panel)
        if group.is_pair:
            menu.addAction(f"Rename '{group.name}'…", lambda: self.rename_pair(index))
            menu.addAction('Unpair', lambda: self.unpair(index))
        else:
            name = group.actuators[0]
            others = [g.actuators[0] for g in self.groups if not g.is_pair and g is not group]
            sub = menu.addMenu(f"Pair '{name}' with")
            sub.setEnabled(bool(others))
            for other in others:
                sub.addAction(other, lambda o=other: self.pair_actuators(name, o))
        return menu

    def _ask_name(self, title: str, default: str) -> Optional[str]:
        text, ok = QtWidgets.QInputDialog.getText(self.mainwindow, title, 'Name of the pair:', text=default)
        return text.strip() if ok else None

    def pair_actuators(self, first: str, second: str, name: Optional[str] = None):
        """Pair two actuators (first: horizontal keys, second: vertical keys) and select the new pair"""
        if name is None:
            name = self._ask_name('New pair', f'{first} / {second}')
            if name is None:
                return
        ui_settings.add_binding(self.settings, Binding.pair(first, second, name), list(self.ports),
                                self._remove_binding)
        self.apply_settings()
        self.select_actuator(first)
        self._set_dirty(True)
        self.panel.setFocus(Qt.OtherFocusReason)

    def _pair_param(self, index: int):
        if not 0 <= index < len(self.groups) or not self.groups[index].is_pair:
            return None
        return ui_settings.pair_group(self.settings, self.groups[index].actuators)

    def rename_pair(self, index: int, name: Optional[str] = None):
        param = self._pair_param(index)
        if param is None:
            return
        if name is None:
            name = self._ask_name('Rename pair', self.groups[index].name)
            if name is None:
                return
        param.child('name').setValue(name)          # value_changed applies it
        self.panel.setFocus(Qt.OtherFocusReason)

    def unpair(self, index: int):
        param = self._pair_param(index)
        if param is not None:
            self._remove_binding(param)

    def _on_step_changed(self, name: str, value: float):
        self.panel.set_step(name, value)
        self.setup.steps[name] = value
        self._loading = True
        try:
            ui_settings.set_step_value(self.settings, name, value)
        finally:
            self._loading = False
        self._set_dirty(True)

    def scale_steps(self, sign: int):
        """'+' (sign > 0) / '-' (sign < 0): scale the steps of the selected group"""
        names = [n for n in self.selected_group() if n in self.ports]
        self.controller.scale_steps(sign, self.setup.step_factor, names)

    def show_message(self, text: str, warning: bool = False, duration_ms: int = 4000):
        self.panel.show_message(text, warning)
        if text and duration_ms:
            self._message_timer.start(duration_ms)
        else:
            self._message_timer.stop()

    # ---------------------------------------------------------------- bindings
    def _add_pair(self):
        ui_settings.add_binding(self.settings, Binding.pair(), list(self.ports), self._remove_binding)
        self.apply_settings()
        self._set_dirty(True)

    def _add_single(self):
        ui_settings.add_binding(self.settings, Binding.single(), list(self.ports), self._remove_binding)
        self.apply_settings()
        self._set_dirty(True)

    def _remove_binding(self, group):
        group.remove()
        self.apply_settings()
        self._set_dirty(True)

    # ---------------------------------------------------------------- setups
    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self._loading = True
        try:
            name = self.setup_name or '(not saved)'
            self.settings.child('setup', 'current').setValue(f'{name} *' if dirty else name)
        finally:
            self._loading = False
        if self.mainwindow is not None:
            self.mainwindow.setWindowTitle(f"Keyboard Jog - {self.setup_name or 'no setup'}{' *' if dirty else ''}")

    def _refresh_saved_list(self):
        self._loading = True
        try:
            ui_settings.set_saved_setups(self.settings, self.store.names(), self.setup_name)
        finally:
            self._loading = False

    def _load_startup_setup(self):
        name = self.store.last
        if not name or not self.store.exists(name):
            self._set_dirty(False)
            return
        try:
            setup = self.store.load(name)
        except Exception as e:
            logger.warning(f"last setup '{name}' not loaded: {e}")
            self._set_dirty(False)
            return
        used = set(setup.displayed) | set(setup.bound_actuators())
        if used and not used & set(self.ports):
            self.show_message(f"Last setup '{name}' not loaded: none of its actuators is in this dashboard",
                              warning=True, duration_ms=0)
            self._set_dirty(False)
            return
        self.load_setup(name, setup)

    def load_setup(self, name: str, setup: JogSetup = None) -> List[str]:
        """Load a named setup; actuators absent from the Dashboard are skipped (returned warnings)"""
        if setup is None:
            setup = self.store.load(name)
        restricted, warnings = setup.restricted_to(list(self.ports))
        self.controller.release_all(stop=False)
        self._auto_display = False
        self._write_tree(restricted)
        self.setup_name = clean_name(name)
        self.store.last = self.setup_name
        self.apply_settings()
        self._set_dirty(False)
        self._refresh_saved_list()
        for w in warnings:
            logger.warning(f"setup '{name}': {w}")
        if warnings:
            self.show_message(f"Setup '{name}' loaded with warnings: " + '; '.join(warnings), warning=True,
                              duration_ms=0)
        else:
            self.show_message(f"Setup '{name}' loaded")
        return warnings

    def save_setup(self, name: str = None) -> Optional[str]:
        name = clean_name(name if name is not None else self.setup_name)
        if not name:
            self.show_message("Type a name in 'New name' and click 'Save as'", warning=True)
            return None
        self.setup_name = self.store.save(name, ui_settings.read_setup(self.settings))
        self._auto_display = False
        self.store.last = self.setup_name
        self._set_dirty(False)
        self._refresh_saved_list()
        self.show_message(f"Setup '{self.setup_name}' saved")
        return self.setup_name

    def delete_setup(self, name: str):
        self.store.delete(name)
        if clean_name(name) == self.setup_name:
            self.setup_name = ''
            self._set_dirty(True)
        self._refresh_saved_list()
        self.show_message(f"Setup '{name}' deleted")

    def _ask(self, title: str, text: str) -> bool:
        answer = QtWidgets.QMessageBox.question(self.mainwindow, title, text,
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    def _load_selected(self):
        name = self.settings['setup', 'saved']
        if not name:
            return
        if self._dirty and not self._ask('Load setup', f"Discard the changes of the current setup and load "
                                                       f"'{name}'?"):
            return
        try:
            self.load_setup(name)
        except Exception as e:
            logger.warning(f"setup '{name}' not loaded: {e}")
            self.show_message(f"Setup '{name}' not loaded: {e}", warning=True)

    def _save_as(self):
        name = clean_name(self.settings['setup', 'new_name'])
        if not name:
            self.show_message("Type a name in 'New name' first", warning=True)
            return
        if self.store.exists(name) and not self._ask('Save setup', f"Replace the setup '{name}'?"):
            return
        if self.save_setup(name):
            self._loading = True
            self.settings.child('setup', 'new_name').setValue('')
            self._loading = False

    def _delete_selected(self):
        name = self.settings['setup', 'saved']
        if name and self._ask('Delete setup', f"Delete the setup '{name}'?"):
            self.delete_setup(name)

    # ---------------------------------------------------------------- window and focus
    def _decorate_window(self):
        """Compact window: no menu, tool or status bar (PyMoDAQ adds them to every extension window)"""
        win = self.mainwindow
        if win is None or self._closing:
            return
        win.menuBar().setVisible(False)
        win.statusBar().setVisible(False)
        for toolbar in win.findChildren(QtWidgets.QToolBar):
            toolbar.setVisible(False)
        self._set_dirty(self._dirty)
        self.apply_always_on_top(self.setup.always_on_top)
        self._fit_window()
        self.panel.setFocus(Qt.OtherFocusReason)

    def apply_always_on_top(self, on: bool):
        win = self.mainwindow
        if win is None:
            return
        if bool(win.windowFlags() & Qt.WindowStaysOnTopHint) == bool(on):
            return
        visible = win.isVisible()
        win.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        if visible:              # changing the flags hides the window: Qt needs it to be shown again
            win.show()
            win.activateWindow()
            self.panel.setFocus(Qt.OtherFocusReason)

    def _on_top_checkbox(self, on: bool):
        self.settings.child('general', 'always_on_top').setValue(on)   # value_changed applies it

    def _on_settings_toggled(self, shown: bool):
        if not shown:
            self.panel.setFocus(Qt.OtherFocusReason)
        for delay_ms in (0, 50):     # the second one once Qt has processed the layout of the hidden settings
            QtCore.QTimer.singleShot(delay_ms, self._fit_window)

    def _fit_window(self):
        win = self.mainwindow
        if win is None:
            return
        if self.panel.settings_visible():
            win.resize(max(win.width(), SETTINGS_SIZE.width()), max(win.height(), SETTINGS_SIZE.height()))
        else:
            widget = self.panel
            while widget is not None:              # up to the window: the hidden settings must not count
                layout = QtWidgets.QWidget.layout(widget)   # pyqtgraph's Dock shadows layout() by an attribute
                if layout is not None:
                    layout.invalidate()
                    layout.activate()
                widget = widget.parentWidget()
            hint = win.minimumSizeHint()
            win.resize(max(hint.width(), COMPACT_SIZE.width()), max(hint.height(), 60))

    def _on_armed_changed(self, armed: bool):
        if not armed:
            self.controller.release_all(stop=self.setup.stop_on_focus_loss)

    # ---------------------------------------------------------------- PyMoDAQ hooks
    def stop(self):
        """Programmatic stop requested by PyMoDAQ: stop repeating and stop the actuators this window moves"""
        if self.panel is not None:
            self.keyboard.reset()
            self.controller.release_all(stop=True)

    def do_things_after_experiment_set(self, experiment_name: str, show_dashboard: bool = None):
        parent = getattr(super(), 'do_things_after_experiment_set', None)
        if parent is not None:
            parent(experiment_name, show_dashboard)
        if self.panel is not None:
            self.refresh_actuators()

    def eventFilter(self, obj, event):
        if obj is getattr(self, 'mainwindow', None) and event.type() == QtCore.QEvent.Close:
            self.shutdown()
        return super().eventFilter(obj, event)

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._modules_timer.stop()
        self.keyboard.reset()
        self.controller.release_all(stop=True)
        for port in self.ports.values():
            port.disconnect()

    def _quit_fun(self) -> bool:
        return True       # PyMoDAQ 5.3: CustomExt.quit_fun does nothing unless this hook returns True

    def quit_fun(self) -> bool:
        self.shutdown()
        try:
            super().quit_fun()
        except Exception:
            pass
        if self.mainwindow is not None:
            self.mainwindow.close()
        return True


def main():
    """Standalone launch for development: ``python -m pymodaq_plugins_keyboardjog.extensions.keyboard_jog <name>``
    where name is a Dashboard preset (PyMoDAQ 5.1) or experiment (5.2+) with actuators."""
    import sys
    try:
        from pymodaq_gui.qt_utils import mkQApp          # pymodaq_gui >= 5.2
    except ImportError:
        from pymodaq_gui.utils.utils import mkQApp       # pymodaq_gui 5.0 / 5.1
    app = mkQApp(EXTENSION_NAME)
    name = sys.argv[1] if len(sys.argv) > 1 else 'keyboard_jog_mock'
    try:  # PyMoDAQ >= 5.2: extensions are designated by the upper-cased class name (ExtensionEnum)
        from pymodaq.dashboard import load_dashboard_with_experiment
        load_dashboard_with_experiment(name, CLASS_NAME.upper())
    except ImportError:  # PyMoDAQ 5.1
        from pymodaq.utils.gui_utils.loader_utils import load_dashboard_with_preset
        load_dashboard_with_preset(name, EXTENSION_NAME)
    sys.exit((getattr(app, 'exec', None) or app.exec_)())


if __name__ == '__main__':
    main()
