"""The compact main view: one row per shown actuator, the focus indicator and the (hidden) settings.

Focus indicator (main safety feature): the panel is *armed* only while it owns the keyboard focus in the active
window. Armed = green border, the keys move the actuators. Not armed = red border, every key is ignored.
Clicking on the panel gives it the focus (and selects the group of the clicked row). Clicking in the settings tree
gives the focus to the tree, so the panel turns red: typing a value never moves an actuator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from qtpy import QtCore, QtGui, QtWidgets

from ..core.input import KeyboardInput

Qt = QtCore.Qt

ARMED_COLOR = '#27ae60'
DISARMED_COLOR = '#c0392b'
WARNING_COLOR = '#d35400'
SELECTED_MARK = '▶'


def hint_text(move_keys_label: str) -> str:
    return f'1-9 or click: select   {move_keys_label}: move   + / -: step   right-click: pair'


@dataclass
class RowInfo:
    """A row of the main view: an actuator, or the header (name) of a pair"""
    label: str
    group: int
    units: str = ''
    number: str = ''                 # group number, on the first row of the group
    actuator: Optional[str] = None   # None: header row of a pair
    indent: bool = False             # actuator of a pair

    @property
    def is_header(self) -> bool:
        return self.actuator is None


def format_value(value: Optional[float], units: str = '', step: Optional[float] = None) -> str:
    """Value with units, with two more decimals than the step (so that one step is always visible)"""
    if value is None:
        return '---'
    if step is not None and step > 0 and abs(value) < 1e9:
        decimals = min(max(0, 2 - int(math.floor(math.log10(step)))), 9)
        text = f'{value:.{decimals}f}'
        if float(text) == 0:
            text = text.lstrip('-')          # no '-0.000' from the noise around zero
    else:
        text = f'{value:.6g}'
    return f'{text} {units}'.strip()


class _Row:
    def __init__(self, grid: QtWidgets.QGridLayout, row: int, info: RowInfo):
        self.info = info
        self.last_value: Optional[float] = None
        self.last_step: Optional[float] = None
        self.number = QtWidgets.QLabel(info.number)
        self.number.setMinimumWidth(22)
        self.name = QtWidgets.QLabel(info.label)
        if info.indent:
            self.name.setIndent(12)
        self.value = QtWidgets.QLabel('' if info.is_header else '---')
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setMinimumWidth(90)
        self.step = QtWidgets.QLabel('')
        self.step.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.keys = QtWidgets.QLabel('')
        for col, label in enumerate(self.labels):
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            grid.addWidget(label, row, col)
        self.step.setStyleSheet('color: gray;')
        self.keys.setStyleSheet('color: gray;')
        self.number.setStyleSheet('color: gray;')

    @property
    def labels(self):
        return self.number, self.name, self.value, self.step, self.keys

    def set_selected(self, selected: bool):
        for label in (self.name, self.number):
            font = label.font()
            font.setBold(selected)
            label.setFont(font)
        marked = selected and not self.info.indent        # a pair is marked on its header only
        self.number.setText(f'{SELECTED_MARK} {self.info.number}'.strip() if marked else self.info.number)
        self.number.setStyleSheet(f'color: {ARMED_COLOR};' if selected else 'color: gray;')
        self.keys.setStyleSheet('' if selected else 'color: gray;')

    def remove(self, grid: QtWidgets.QGridLayout):
        for label in self.labels:
            grid.removeWidget(label)
            label.hide()             # never setParent(None): the label would become a top-level window
            label.deleteLater()


class JogPanel(QtWidgets.QFrame):
    armed_changed = QtCore.Signal(bool)
    settings_toggled = QtCore.Signal(bool)
    always_on_top_toggled = QtCore.Signal(bool)
    group_clicked = QtCore.Signal(int)
    context_requested = QtCore.Signal(int, str, QtCore.QPoint)   # group, actuator ('' = pair header), global pos

    def __init__(self, keyboard: KeyboardInput, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.keyboard = keyboard
        self.setObjectName('jog_panel')
        self.setFocusPolicy(Qt.StrongFocus)
        self._armed: Optional[bool] = None
        self._rows: Dict[str, _Row] = {}          # actuator rows
        self._headers: Dict[int, _Row] = {}       # pair header rows, per group

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        self.state_label = QtWidgets.QLabel('')
        self.mode_label = QtWidgets.QLabel('')
        self.mode_label.setStyleSheet('color: gray;')
        self.on_top_check = QtWidgets.QCheckBox('On top')
        self.on_top_check.setChecked(True)
        self.on_top_check.setToolTip('Keep this window above the other windows')
        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setText('Settings')
        self.settings_button.setCheckable(True)
        self.settings_button.setAutoRaise(True)
        self.settings_button.setToolTip('Show / hide the settings')
        for w in (self.on_top_check, self.settings_button):
            w.setFocusPolicy(Qt.NoFocus)     # clicking them must not take the focus from the panel
        header.addWidget(self.state_label)
        header.addStretch()
        header.addWidget(self.mode_label)
        header.addWidget(self.on_top_check)
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        self.rows_widget = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.rows_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(1)
        layout.addWidget(self.rows_widget)

        self.empty_label = QtWidgets.QLabel('No actuator in the Dashboard (or none displayed: see the settings).')
        self.empty_label.setStyleSheet('color: gray;')
        layout.addWidget(self.empty_label)

        self.hint_label = QtWidgets.QLabel(hint_text('W A S D'))
        self.hint_label.setStyleSheet('color: gray; font-size: 8pt;')
        layout.addWidget(self.hint_label)

        self.message_label = QtWidgets.QLabel('')
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        layout.addWidget(self.message_label)

        self.settings_container = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self.settings_container).setContentsMargins(0, 4, 0, 0)
        self.settings_container.setVisible(False)
        layout.addWidget(self.settings_container, 1)

        self.on_top_check.toggled.connect(self.always_on_top_toggled.emit)
        self.settings_button.toggled.connect(self._toggle_settings)

        self._watchdog = QtCore.QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self.update_armed)
        self._watchdog.start()
        self.update_armed()

    # ------------------------------------------------------------------ content
    def set_settings_widget(self, widget: QtWidgets.QWidget):
        self.settings_container.layout().addWidget(widget)

    def settings_visible(self) -> bool:
        return self.settings_button.isChecked()

    def show_settings(self, show: bool):
        self.settings_button.setChecked(show)

    def _toggle_settings(self, show: bool):
        self.settings_container.setVisible(show)
        self.settings_toggled.emit(show)

    def set_rows(self, rows: Iterable[RowInfo]):
        for row in list(self._rows.values()) + list(self._headers.values()):
            row.remove(self.grid)
        self._rows = {}
        self._headers = {}
        for i, info in enumerate(rows):
            row = _Row(self.grid, i, info)
            if info.is_header:
                self._headers[info.group] = row
            else:
                self._rows[info.actuator] = row
        self.empty_label.setVisible(not self._rows)
        self.hint_label.setVisible(bool(self._rows))

    def set_hint(self, move_keys_label: str):
        self.hint_label.setText(hint_text(move_keys_label))

    def row_names(self) -> List[str]:
        return list(self._rows)

    def header_text(self, group: int) -> str:
        row = self._headers.get(group)
        return row.name.text() if row is not None else ''

    def set_selected(self, group: int):
        for row in list(self._rows.values()) + list(self._headers.values()):
            row.set_selected(row.info.group == group)

    def selected_names(self) -> List[str]:
        return [name for name, row in self._rows.items() if row.name.font().bold()]

    def set_keys(self, name: str, text: str):
        row = self._rows.get(name)
        if row is not None:
            row.keys.setText(text)

    def keys_text(self, name: str) -> str:
        row = self._rows.get(name)
        return row.keys.text() if row is not None else ''

    def set_value(self, name: str, value: Optional[float]):
        row = self._rows.get(name)
        if row is not None:
            row.last_value = value
            row.value.setText(format_value(value, row.info.units, row.last_step))

    def value_text(self, name: str) -> str:
        row = self._rows.get(name)
        return row.value.text() if row is not None else ''

    def set_step(self, name: str, step: float):
        row = self._rows.get(name)
        if row is not None:
            row.last_step = step
            row.step.setText(f'step {step:.4g}')
            row.value.setText(format_value(row.last_value, row.info.units, step))

    def step_text(self, name: str) -> str:
        row = self._rows.get(name)
        return row.step.text() if row is not None else ''

    def set_mode_text(self, text: str):
        self.mode_label.setText(text)

    def show_message(self, text: str, warning: bool = False):
        self.message_label.setText(text)
        self.message_label.setStyleSheet(f'color: {WARNING_COLOR};' if warning else 'color: gray;')
        self.message_label.setVisible(bool(text))

    def row_at(self, pos: QtCore.QPoint) -> Optional[RowInfo]:
        child = self.childAt(pos)
        for row in list(self._rows.values()) + list(self._headers.values()):
            if child in row.labels:
                return row.info
        return None

    # ------------------------------------------------------------------ focus / armed state
    @property
    def armed(self) -> bool:
        return bool(self._armed)

    def update_armed(self):
        armed = self.isVisible() and self.isActiveWindow() and self.hasFocus()
        if armed == self._armed:
            return
        self._armed = armed
        color = ARMED_COLOR if armed else DISARMED_COLOR
        self.setStyleSheet(f'#jog_panel {{ border: 3px solid {color}; border-radius: 4px; }}')
        self.state_label.setText('● ACTIVE' if armed else '● click here to activate')
        self.state_label.setStyleSheet(f'color: {color}; font-weight: bold;')
        if not armed:
            self.keyboard.reset()
        self.armed_changed.emit(armed)

    def focusInEvent(self, event: QtGui.QFocusEvent):
        super().focusInEvent(event)
        self.update_armed()

    def focusOutEvent(self, event: QtGui.QFocusEvent):
        super().focusOutEvent(event)
        self.update_armed()

    def changeEvent(self, event: QtCore.QEvent):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.ActivationChange:
            self.update_armed()

    def hideEvent(self, event: QtGui.QHideEvent):
        super().hideEvent(event)
        self.update_armed()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        self.setFocus(Qt.MouseFocusReason)
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        info = self.row_at(pos)
        if info is not None and event.button() == Qt.LeftButton:
            self.group_clicked.emit(info.group)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        info = self.row_at(event.pos())
        if info is None:
            super().contextMenuEvent(event)
            return
        self.setFocus(Qt.MouseFocusReason)
        self.group_clicked.emit(info.group)
        self.context_requested.emit(info.group, info.actuator or '', event.globalPos())
        event.accept()

    # ------------------------------------------------------------------ keys
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        self.update_armed()
        if self.armed and self.keyboard.key_press(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent):
        if self.keyboard.key_release(event):     # releasing is always safe: processed even when not armed
            event.accept()
            return
        super().keyReleaseEvent(event)
