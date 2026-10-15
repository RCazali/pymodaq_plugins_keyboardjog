"""The compact main view: one line per group, the focus indicator, the (hidden) history and settings.

Layout: one line per group (number, name, horizontal value, vertical value, units), in columns of at most 5 lines
(6 groups: 3 + 3, 10 groups: 5 + 5). The values are right-aligned in a fixed-width font, with a fixed number of
decimals per actuator (from its step), so that they do not move. A headless actuator shows no value (its name turns
orange while it moves). The step, mode and keys of the selected group only are shown in the detail line below.
The history plot is on the right side.

Focus indicator (main safety feature): the panel is *armed* only while it owns the keyboard focus in the active
window. Armed = green border, the keys move the actuators. Not armed = red border, every key is ignored.
Clicking on the panel gives it the focus (and selects the group of the clicked line). Clicking in the settings tree
gives the focus to the tree, so the panel turns red: typing a value never moves an actuator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from qtpy import QtCore, QtGui, QtWidgets

from ..core.input import KeyboardInput

Qt = QtCore.Qt

ARMED_COLOR = '#27ae60'
DISARMED_COLOR = '#c0392b'
WARNING_COLOR = '#d35400'
BUSY_STYLE = 'background-color: #e67e22; color: white; border-radius: 3px; padding: 0px 3px;'
IDLE_STYLE = 'padding: 0px 3px;'
SELECTED_MARK = '▶'
MAX_LINES = 5            # lines per column of groups
COLUMNS_PER_BLOCK = 6    # number, name, horizontal, vertical, units, gap
H_ARROW, V_ARROW = '↔', '↕'


def hint_text(move_keys_label: str) -> str:
    return f'1-9, 0 or click: select   {move_keys_label}: move   + / -: step   right-click: options'


def history_icon(shown: bool) -> Optional[QtGui.QIcon]:
    """The 'graph' icon of the DAQ_Move modules (PyMoDAQ 5.3 Material icon, 5.1 png), None if not found"""
    try:
        from pymodaq_gui.managers.action_manager import create_icon
    except ImportError:  # pragma: no cover
        return None
    color = ARMED_COLOR if shown else 'gray'
    for name in ('bid_landscape' if shown else 'bid_landscape_disabled', 'graph'):
        for kwargs in ({'icon_color': color}, {}):        # 5.1: no color argument
            try:
                icon = create_icon(name, **kwargs)
            except Exception:
                continue
            if icon is not None and not icon.isNull():
                return icon
    return None


def grid_shape(count: int, max_lines: int = MAX_LINES) -> Tuple[int, int]:
    """(columns, lines per column) for this number of groups: 10 -> 2 x 5, 6 -> 2 x 3, 4 -> 1 x 4, 11 -> 3 x 4"""
    if count <= 0:
        return 0, 0
    columns = math.ceil(count / max_lines)
    return columns, math.ceil(count / columns)


def value_decimals(step: Optional[float]) -> Optional[int]:
    """Two more decimals than the step (so that one step is always visible), None if the step is unknown"""
    if step is None or step <= 0:
        return None
    return min(max(0, 2 - int(math.floor(math.log10(step)))), 9)


def format_value(value: Optional[float], units: str = '', step: Optional[float] = None) -> str:
    """Value with a fixed number of decimals given by the step (and units)"""
    if value is None:
        return '---'
    decimals = value_decimals(step)
    if decimals is not None and abs(value) < 1e9:
        text = f'{value:.{decimals}f}'
        if float(text) == 0:
            text = text.lstrip('-')          # no '-0.000' from the noise around zero
    else:
        text = f'{value:.6g}'
    return f'{text} {units}'.strip()


@dataclass
class GroupRow:
    """A line of the main view: one group (a single actuator or a pair)"""
    index: int
    number: str
    title: str
    horizontal: Optional[str] = None
    vertical: Optional[str] = None
    units: Dict[str, str] = field(default_factory=dict)
    headless: Set[str] = field(default_factory=set)
    tooltip: str = ''

    @property
    def actuators(self) -> List[str]:
        return [a for a in (self.horizontal, self.vertical) if a]

    def units_text(self) -> str:
        """Units once for the line ('mm', or 'µm / mm' when they differ), none for the headless actuators"""
        units = []
        for name in self.actuators:
            unit = self.units.get(name, '')
            if name not in self.headless and unit and unit not in units:
                units.append(unit)
        return ' / '.join(units)


class _Line:
    """The labels of one group line"""

    def __init__(self, grid: QtWidgets.QGridLayout, line: int, column: int, info: GroupRow, value_font: QtGui.QFont):
        self.info = info
        self.number = QtWidgets.QLabel(info.number)
        self.number.setMinimumWidth(22)
        self.name = QtWidgets.QLabel(info.title)
        self.values = {}
        for name in info.actuators:
            label = QtWidgets.QLabel('' if name in info.headless else '---')
            label.setFont(value_font)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setStyleSheet(IDLE_STYLE)
            self.values[name] = label
        self.h_value = self.values.get(info.horizontal) or QtWidgets.QLabel('')
        self.v_value = self.values.get(info.vertical) or QtWidgets.QLabel('')
        self.units = QtWidgets.QLabel(info.units_text())
        self.units.setStyleSheet('color: gray;')
        base = column * COLUMNS_PER_BLOCK
        for offset, label in enumerate(self.labels):
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            label.setToolTip(info.tooltip)
            grid.addWidget(label, line, base + offset)
        self.number.setStyleSheet('color: gray;')
        self.name.setStyleSheet(IDLE_STYLE)

    @property
    def labels(self):
        return self.number, self.name, self.h_value, self.v_value, self.units

    def actuator_at(self, widget) -> str:
        for name, label in self.values.items():
            if label is widget:
                return name
        return ''

    def set_selected(self, selected: bool):
        for label in (self.name, self.number):
            font = label.font()
            font.setBold(selected)
            label.setFont(font)
        self.number.setText(f'{SELECTED_MARK} {self.info.number}'.strip() if selected else self.info.number)
        self.number.setStyleSheet(f'color: {ARMED_COLOR};' if selected else 'color: gray;')

    def remove(self, grid: QtWidgets.QGridLayout):
        for label in self.labels:
            grid.removeWidget(label)
            label.hide()             # never setParent(None): the label would become a top-level window
            label.deleteLater()


class JogPanel(QtWidgets.QFrame):
    armed_changed = QtCore.Signal(bool)
    settings_toggled = QtCore.Signal(bool)
    history_toggled = QtCore.Signal(bool)
    always_on_top_toggled = QtCore.Signal(bool)
    close_requested = QtCore.Signal()
    group_clicked = QtCore.Signal(int)
    context_requested = QtCore.Signal(int, str, QtCore.QPoint)   # group, actuator ('' = the line), global pos

    def __init__(self, keyboard: KeyboardInput, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.keyboard = keyboard
        self.setObjectName('jog_panel')
        self.setFocusPolicy(Qt.StrongFocus)
        self._armed: Optional[bool] = None
        self._lines: List[_Line] = []
        self._line_of: Dict[str, _Line] = {}       # actuator -> its line
        self._arrows: List[QtWidgets.QLabel] = []   # ↔ ↕ column headers
        self._values: Dict[str, Optional[float]] = {}
        self._steps: Dict[str, float] = {}
        self._busy: Set[str] = set()
        self._value_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        self.state_label = QtWidgets.QLabel('')
        self.mode_label = QtWidgets.QLabel('')
        self.mode_label.setStyleSheet(f'color: {WARNING_COLOR}; font-weight: bold;')
        self.on_top_check = QtWidgets.QCheckBox('On top')
        self.on_top_check.setChecked(True)
        self.on_top_check.setToolTip('Keep this window above the other windows')
        self.history_button = QtWidgets.QToolButton()
        self.history_button.setCheckable(True)
        self.history_button.setAutoRaise(True)
        self.history_button.setToolTip('Show / hide the history of the moves of the selected group')
        self._update_history_icon(False)
        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setText('Settings')
        self.settings_button.setCheckable(True)
        self.settings_button.setAutoRaise(True)
        self.settings_button.setToolTip('Show / hide the settings')
        self.close_button = QtWidgets.QToolButton()
        self.close_button.setText('✕')
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip('Close Keyboard Jog (the moves it started are stopped)')
        for w in (self.on_top_check, self.history_button, self.settings_button, self.close_button):
            w.setFocusPolicy(Qt.NoFocus)     # clicking them must not take the focus from the panel
        header.addWidget(self.state_label)
        header.addStretch()
        header.addWidget(self.mode_label)
        header.addWidget(self.on_top_check)
        header.addWidget(self.history_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(8)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(2)
        self.rows_widget = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.rows_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(1)
        left.addWidget(self.rows_widget)

        self.empty_label = QtWidgets.QLabel('No actuator in the Dashboard (or all hidden: see the settings).')
        self.empty_label.setStyleSheet('color: gray;')
        left.addWidget(self.empty_label)

        self.detail_label = QtWidgets.QLabel('')
        self.detail_label.setToolTip('Keys, step and motion mode of the selected group')
        left.addWidget(self.detail_label)

        self.hint_label = QtWidgets.QLabel(hint_text('W A S D'))
        self.hint_label.setStyleSheet('color: gray; font-size: 8pt;')
        left.addWidget(self.hint_label)

        self.message_label = QtWidgets.QLabel('')
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        left.addWidget(self.message_label)
        left.addStretch()
        body.addLayout(left)

        self.history_container = QtWidgets.QWidget()
        self.history_container.setMinimumWidth(280)
        QtWidgets.QVBoxLayout(self.history_container).setContentsMargins(0, 0, 0, 0)
        self.history_container.setVisible(False)
        body.addWidget(self.history_container, 1)
        layout.addLayout(body)

        self.settings_container = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self.settings_container).setContentsMargins(0, 4, 0, 0)
        self.settings_container.setVisible(False)
        layout.addWidget(self.settings_container, 1)

        self.on_top_check.toggled.connect(self.always_on_top_toggled.emit)
        self.history_button.toggled.connect(self._toggle_history)
        self.settings_button.toggled.connect(self._toggle_settings)
        self.close_button.clicked.connect(self.close_requested.emit)

        self._watchdog = QtCore.QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self.update_armed)
        self._watchdog.start()
        self.update_armed()

    # ------------------------------------------------------------------ settings / history containers
    def set_settings_widget(self, widget: QtWidgets.QWidget):
        self.settings_container.layout().addWidget(widget)

    def settings_visible(self) -> bool:
        return self.settings_button.isChecked()

    def show_settings(self, show: bool):
        self.settings_button.setChecked(show)

    def _toggle_settings(self, show: bool):
        self.settings_container.setVisible(show)
        self.settings_toggled.emit(show)

    def set_history_widget(self, widget: QtWidgets.QWidget):
        self.history_container.layout().addWidget(widget)

    def history_visible(self) -> bool:
        return self.history_button.isChecked()

    def show_history(self, show: bool):
        self.history_button.setChecked(show)

    def _toggle_history(self, show: bool):
        self.history_container.setVisible(show)
        self._update_history_icon(show)
        self.history_toggled.emit(show)

    def _update_history_icon(self, shown: bool):
        icon = history_icon(shown)
        if icon is not None:
            self.history_button.setIcon(icon)
            self.history_button.setText('')
        else:
            self.history_button.setText('History')

    # ------------------------------------------------------------------ lines
    def set_rows(self, rows: Iterable[GroupRow]):
        """One line per group, in columns of at most MAX_LINES lines"""
        for line in self._lines:
            line.remove(self.grid)
        for label in self._arrows:
            self.grid.removeWidget(label)
            label.hide()
            label.deleteLater()
        self._lines, self._line_of, self._arrows = [], {}, []
        for column in range(self.grid.columnCount()):
            self.grid.setColumnMinimumWidth(column, 0)
        rows = list(rows)
        columns, lines = grid_shape(len(rows))
        any_h = any(r.horizontal and r.horizontal not in r.headless for r in rows)
        any_v = any(r.vertical and r.vertical not in r.headless for r in rows)
        for column in range(columns):
            base = column * COLUMNS_PER_BLOCK
            for offset, arrow, shown in ((2, H_ARROW, any_h), (3, V_ARROW, any_v)):
                label = QtWidgets.QLabel(arrow if shown else '')
                label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
                label.setStyleSheet('color: gray; font-size: 8pt;')
                label.setToolTip('horizontal (left / right keys)' if arrow == H_ARROW else 'vertical (down / up keys)')
                self.grid.addWidget(label, 0, base + offset)
                self._arrows.append(label)
            if column:
                self.grid.setColumnMinimumWidth(base - 1, 12)        # gap between two columns of groups
        for i, info in enumerate(rows):
            line = _Line(self.grid, 1 + i % lines, i // lines, info, self._value_font)
            self._lines.append(line)
            for name in info.actuators:
                self._line_of[name] = line
                self._show_value(name)
                self._show_busy(name)
        self.empty_label.setVisible(not rows)
        self.hint_label.setVisible(bool(rows))
        self.detail_label.setVisible(bool(rows))
        for label in self._arrows:
            label.setVisible(any_h or any_v)

    def set_hint(self, move_keys_label: str):
        self.hint_label.setText(hint_text(move_keys_label))

    def row_names(self) -> List[str]:
        """The actuators of the lines, in the line order"""
        return [name for line in self._lines for name in line.info.actuators]

    def line_count(self) -> int:
        return len(self._lines)

    def line_position(self, index: int) -> Tuple[int, int]:
        """(grid row, grid column) of the line of the group of this index"""
        for line in self._lines:
            if line.info.index == index:
                row, column, _, _ = self.grid.getItemPosition(self.grid.indexOf(line.number))
                return row, column // COLUMNS_PER_BLOCK
        return -1, -1

    def header_text(self, index: int) -> str:
        for line in self._lines:
            if line.info.index == index:
                return line.name.text()
        return ''

    def set_selected(self, index: int):
        for line in self._lines:
            line.set_selected(line.info.index == index)

    def selected_names(self) -> List[str]:
        return [name for line in self._lines if line.name.font().bold() for name in line.info.actuators]

    def set_detail(self, text: str):
        self.detail_label.setText(text)

    def detail_text(self) -> str:
        return self.detail_label.text()

    # ------------------------------------------------------------------ values
    def set_value(self, name: str, value: Optional[float]):
        self._values[name] = value
        self._show_value(name)

    def set_step(self, name: str, step: float):
        self._steps[name] = step
        self._show_value(name)

    def _show_value(self, name: str):
        line = self._line_of.get(name)
        if line is None or name in line.info.headless:
            return
        label = line.values[name]
        text = format_value(self._values.get(name), '', self._steps.get(name))
        label.setText(text)
        width = QtGui.QFontMetrics(label.font()).horizontalAdvance(text) + 8
        if width > label.minimumWidth():          # grows, never shrinks: the columns do not jump
            label.setMinimumWidth(width)

    def value_text(self, name: str) -> str:
        line = self._line_of.get(name)
        return line.values[name].text() if line is not None else ''

    def set_busy(self, name: str, busy: bool):
        """Value (or name of a headless actuator) highlighted while the actuator moves"""
        if busy:
            self._busy.add(name)
        else:
            self._busy.discard(name)
        self._show_busy(name)

    def _show_busy(self, name: str):
        line = self._line_of.get(name)
        if line is None:
            return
        busy = name in self._busy
        if name in line.info.headless:
            moving = any(a in self._busy for a in line.info.actuators if a in line.info.headless)
            line.name.setStyleSheet(BUSY_STYLE if moving else IDLE_STYLE)
        else:
            line.values[name].setStyleSheet(BUSY_STYLE if busy else IDLE_STYLE)

    def is_busy_shown(self, name: str) -> bool:
        line = self._line_of.get(name)
        if line is None:
            return False
        label = line.name if name in line.info.headless else line.values[name]
        return label.styleSheet() == BUSY_STYLE

    def set_mode_text(self, text: str):
        self.mode_label.setText(text)

    def show_message(self, text: str, warning: bool = False):
        self.message_label.setText(text)
        self.message_label.setStyleSheet(f'color: {WARNING_COLOR};' if warning else 'color: gray;')
        self.message_label.setVisible(bool(text))

    def line_at(self, pos: QtCore.QPoint) -> Tuple[Optional[GroupRow], str]:
        """(group line, actuator of the clicked value or '') at this position of the panel"""
        child = self.childAt(pos)
        for line in self._lines:
            if child in line.labels:
                return line.info, line.actuator_at(child)
        return None, ''

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
        info, _ = self.line_at(pos)
        if info is not None and event.button() == Qt.LeftButton:
            self.group_clicked.emit(info.index)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        info, actuator = self.line_at(event.pos())
        if info is None:
            super().contextMenuEvent(event)
            return
        self.setFocus(Qt.MouseFocusReason)
        self.group_clicked.emit(info.index)
        self.context_requested.emit(info.index, actuator, event.globalPos())
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
