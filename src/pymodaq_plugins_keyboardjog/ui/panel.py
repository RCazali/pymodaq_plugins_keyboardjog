"""The compact main view: one line per group, the focus indicator, the (hidden) history and settings.

Layout: one line per group (colored number, name, horizontal value, vertical value, units), in columns of at most 5
lines (6 groups: 3 + 3, 10 groups: 5 + 5). The values are right-aligned in a fixed-width font, with a fixed number of
decimals per actuator (chosen, or from its step), so that they do not move. An *active* actuator (e.g. a PID setpoint
while its PID runs, see ``set_active``) has its line in green.

Tooltips are one line: verbose (default, a few words more and a pointer to the ? button) or concise, chosen in the
menu of the ? button, which also opens the full help. The selected line is on a light band, the others are
dimmed. A headless actuator shows no value (its name turns orange while it moves). The keys, steps, mode and
displacement since the selection of the selected group only are in the detail line below. The history plot is on
the right side.

Focus indicator (main safety feature): the panel is *armed* only while it owns the keyboard focus in the active
window. Armed = green border, the keys move the actuators. Not armed = red border, every key is ignored.
Clicking on the panel gives it the focus (and selects the group of the clicked line). Clicking in the settings tree
gives the focus to the tree, so the panel turns red: typing a value never moves an actuator.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from qtpy import QtCore, QtGui, QtWidgets

from ..core.input import KeyboardInput
from ..core.model import TIPS_CONCISE, TIPS_VERBOSE

Qt = QtCore.Qt

ARMED_COLOR = '#27ae60'
DISARMED_COLOR = '#c0392b'
WARNING_COLOR = '#d35400'
BUSY_BACKGROUND = '#e67e22'
SELECTION_BAND = 'rgba(39, 174, 96, 30)'
#: muted colors of the group numbers (also the color of the group in the history)
GROUP_COLORS = ('#5b8db8', '#d9895b', '#6aa56a', '#c96a6a', '#8c7bb5', '#a68662', '#c27aa8', '#5fa8a8',
                '#b8a54f', '#7f8c99', '#5f9ec9', '#b5756f')
MAX_LINES = 5            # lines per column of groups
COLUMNS_PER_BLOCK = 6    # number, name, horizontal, vertical, units, gap


VERBOSE_SUFFIX = '  (?: shorter tips)'

#: tooltips of the panel widgets: (verbose, concise), one line each
TIPS = {
    'close': ('Close Keyboard Jog: the moves it started are stopped', 'Close'),
    'on_top': ('Keep this window above the other windows', 'On top'),
    'positions': ('Saved positions of the selection: go to one, save the current one', 'Saved positions'),
    'history': ('History of the moves of the selection: click a point to go back', 'History'),
    'settings': ('Settings: actuators, keys, motion, setups', 'Settings'),
    'help': ('Help, and verbose / concise tooltips', 'Help'),
    'state': ('Green: the keys move the actuators. Red: keys ignored, click to activate', 'Green: keys active'),
    'detail': ('Selection: keys, step, Δ since selected. Shift: step ×10, Ctrl: ÷10', 'Shift ×10 · Ctrl ÷10'),
}


def tip_text(verbose: str, concise: str, mode: str) -> str:
    """The tooltip of this mode ('' stays '')"""
    if mode == TIPS_CONCISE:
        return concise
    return f'{verbose}{VERBOSE_SUFFIX}' if verbose else ''


def line_tips(number: str, move_keys_label: str) -> Tuple[str, str]:
    """(verbose, concise) tooltip of a group line"""
    select = f'Key {number} or click: select' if number else 'Click: select'
    return f'{select} · {move_keys_label}: move · right-click: options', 'Right-click: options'


def hint_text(move_keys_label: str) -> str:
    """Full help of the generic keys (the ? button)"""
    return (f'Green border: the keys move the actuators. Red: keys ignored, click the window to activate.\n\n'
            f'1-9, 0 and the two keys right of 0 (or a click): select a group. Again: reset Δ.\n'
            f'{move_keys_label}: move the selection (A/D horizontal actuator, S/W vertical one).\n'
            f'Shift held: step × the step factor (fast speed in continuous jog). Ctrl held: step ÷ the factor.\n'
            f'Right-click a line: number, rename, pair, digits, keys, continuous, headless, hide.\n'
            f'Graph button: history of the moves (click a point to go back). Target button: saved positions.\n'
            f'Settings: per actuator step, speeds, extra keys; setups saved by name.')


def group_color(index: int) -> str:
    return GROUP_COLORS[index % len(GROUP_COLORS)]


def pymodaq_icon(names: Iterable[str], color: str) -> Optional[QtGui.QIcon]:
    """The first PyMoDAQ icon found (5.3 Material icons, in this color; 5.1 png icons), None if none is found"""
    try:
        from pymodaq_gui.managers.action_manager import create_icon
    except ImportError:  # pragma: no cover
        return None
    for name in names:
        for kwargs in ({'icon_color': color}, {}):        # 5.1: no color argument
            try:
                icon = create_icon(name, **kwargs)
            except Exception:
                continue
            if icon is not None and not icon.isNull():
                return icon
    return None


def history_icon(shown: bool) -> Optional[QtGui.QIcon]:
    """The 'graph' icon of the DAQ_Move modules"""
    return pymodaq_icon(('bid_landscape' if shown else 'bid_landscape_disabled', 'graph'),
                        ARMED_COLOR if shown else 'gray')


def close_icon() -> Optional[QtGui.QIcon]:
    """The red 'Quit' icon of the PyMoDAQ 5.3 windows ('close2' in 5.1)"""
    return pymodaq_icon(('cancel', 'close2'), DISARMED_COLOR)


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


def format_value(value: Optional[float], units: str = '', step: Optional[float] = None,
                 decimals: Optional[int] = None) -> str:
    """Value with a fixed number of decimals: the given one, else from the step (and units)"""
    if value is None:
        return '---'
    if decimals is None:
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
    color: str = ''

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


@dataclass
class DetailItem:
    """One actuator in the detail line: its key groups (shown as key caps: movement keys, extra keys) and a text
    (step, mode, Δ)"""
    keys: Sequence[Sequence[str]]
    text: str

    def plain(self) -> str:
        return f"{' '.join('/'.join(group) for group in self.keys)} {self.text}".strip()


class _Line:
    """The labels of one group line"""

    def __init__(self, grid: QtWidgets.QGridLayout, line: int, column: int, info: GroupRow, value_font: QtGui.QFont):
        self.info = info
        self.selected = False
        self.number = QtWidgets.QLabel(info.number or '·')
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setFixedWidth(18)
        self.number.setStyleSheet(f'background-color: {info.color or "gray"}; color: white; border-radius: 3px; '
                                  f'font-weight: bold;')
        self.name = QtWidgets.QLabel(info.title)
        self.values: Dict[str, QtWidgets.QLabel] = {}
        for name in info.actuators:
            label = QtWidgets.QLabel('' if name in info.headless else '---')
            label.setFont(value_font)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.values[name] = label
        self.h_value = self.values.get(info.horizontal) or QtWidgets.QLabel('')
        self.v_value = self.values.get(info.vertical) or QtWidgets.QLabel('')
        self.units = QtWidgets.QLabel(info.units_text())
        base = column * COLUMNS_PER_BLOCK
        for offset, label in enumerate(self.labels):
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            label.setToolTip(info.tooltip)
            grid.addWidget(label, line, base + offset)
        self.grid_position = (line, base)

    @property
    def labels(self):
        return self.number, self.name, self.h_value, self.v_value, self.units

    def actuator_at(self, widget) -> str:
        for name, label in self.values.items():
            if label is widget:
                return name
        return ''

    def is_busy_label(self, label: QtWidgets.QLabel) -> bool:
        return bool(label.property('busy'))

    def apply_style(self, busy: Set[str], normal: str, muted: str, value_font: QtGui.QFont,
                    active: Set[str] = frozenset()):
        """Selected: normal color, bold name, values one point larger. Others dimmed. Moving: orange background.
        Active (e.g. a running regulation): green"""
        color = normal if self.selected else muted
        if any(a in active for a in self.info.actuators):
            color = ARMED_COLOR
        font = QtGui.QFont(self.name.font())
        font.setBold(self.selected)
        self.name.setFont(font)
        big = QtGui.QFont(value_font)
        if self.selected and value_font.pointSizeF() > 0:
            big.setPointSizeF(value_font.pointSizeF() + 1)
        headless_busy = any(a in busy for a in self.info.actuators if a in self.info.headless)
        self._style(self.name, color, headless_busy)
        for name, label in self.values.items():
            label.setFont(big)
            self._style(label, color, name in busy and name not in self.info.headless)
        self.units.setStyleSheet(f'color: {muted};')

    @staticmethod
    def _style(label: QtWidgets.QLabel, color: str, busy: bool):
        label.setProperty('busy', busy)
        if busy:
            label.setStyleSheet(f'background-color: {BUSY_BACKGROUND}; color: white; border-radius: 3px; '
                                f'padding: 0px 3px;')
        else:
            label.setStyleSheet(f'color: {color}; padding: 0px 3px;')

    def remove(self, grid: QtWidgets.QGridLayout):
        for label in self.labels:
            grid.removeWidget(label)
            label.hide()             # never setParent(None): the label would become a top-level window
            label.deleteLater()


class KeyToast(QtWidgets.QLabel):
    """Pressed keys display (demos, teaching): the keys and their effect in a bubble at the bottom of the panel,
    hidden after a moment; the same message repeated shows a counter (×3)"""
    DURATION_MS = 1800

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.setTextFormat(Qt.RichText)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet('background-color: rgba(30, 30, 46, 225); color: white; border-radius: 6px; '
                           'padding: 3px 10px;')
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() + 1)
        self.setFont(font)
        self.hide()
        self._message = ''
        self._count = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_keys(self, keys: Sequence[str], text: str):
        message = '+'.join(keys) + '|' + text
        self._count = self._count + 1 if message == self._message and self.isVisible() else 1
        self._message = message
        caps = '&nbsp;+&nbsp;'.join(f"<span style='background-color:#585b70; color:white;'>&nbsp;{html.escape(k)}"
                                    f"&nbsp;</span>" for k in keys)
        count = f"&nbsp;&nbsp;<span style='color:#a6adc8;'>×{self._count}</span>" if self._count > 1 else ''
        self.setText(f"{caps}&nbsp;&nbsp;{html.escape(text)}{count}")
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self._timer.start(self.DURATION_MS)

    def plain_text(self) -> str:
        return self._message.replace('|', ' ') if self.isVisible() else ''

    def place(self):
        """In the line kept free for it at the bottom of the lines (it never covers the values)"""
        parent = self.parentWidget()
        anchor = getattr(parent, 'toast_space', None)
        if anchor is not None and anchor.isVisible():
            top_left = anchor.mapTo(parent, QtCore.QPoint(0, 0))
            self.move(top_left.x(), top_left.y() + max(0, (anchor.height() - self.height()) // 2))
        elif parent is not None:
            self.move(max(4, (parent.width() - self.width()) // 2), max(4, parent.height() - self.height() - 8))


class JogPanel(QtWidgets.QFrame):
    armed_changed = QtCore.Signal(bool)
    settings_toggled = QtCore.Signal(bool)
    history_toggled = QtCore.Signal(bool)
    always_on_top_toggled = QtCore.Signal(bool)
    close_requested = QtCore.Signal()
    positions_requested = QtCore.Signal(QtCore.QPoint)        # global position of the positions button
    group_clicked = QtCore.Signal(int)
    context_requested = QtCore.Signal(int, str, QtCore.QPoint)   # group, actuator ('' = the line), global pos
    tips_mode_changed = QtCore.Signal(str)

    def __init__(self, keyboard: KeyboardInput, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.keyboard = keyboard
        self.setObjectName('jog_panel')
        self.setFocusPolicy(Qt.StrongFocus)
        self._armed: Optional[bool] = None
        self._lines: List[_Line] = []
        self._line_of: Dict[str, _Line] = {}       # actuator -> its line
        self._values: Dict[str, Optional[float]] = {}
        self._steps: Dict[str, float] = {}
        self._busy: Set[str] = set()
        self._selected = -1
        self._detail_plain = ''
        self._value_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self._decimals: Dict[str, Optional[int]] = {}      # chosen digits per actuator (None: from the step)
        self._active: Set[str] = set()
        self.tips_mode = TIPS_VERBOSE
        self._tips: Dict[QtWidgets.QWidget, Tuple[str, str]] = {}
        self._move_keys_label = 'W A S D'
        self.help_text = hint_text(self._move_keys_label)   # full help of the ? button (set by the extension)
        self._help_box: Optional[QtWidgets.QMessageBox] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        self.close_button = self._tool_button(close_icon(), '✕', '')
        if self.close_button.icon().isNull():
            self.close_button.setStyleSheet(f'color: {DISARMED_COLOR}; font-weight: bold;')
        self.state_label = QtWidgets.QLabel('')
        self.mode_label = QtWidgets.QLabel('')
        self.mode_label.setStyleSheet(f'color: {WARNING_COLOR}; font-weight: bold;')
        self.on_top_check = QtWidgets.QCheckBox('On top')
        self.on_top_check.setChecked(True)
        self.on_top_check.setFocusPolicy(Qt.NoFocus)
        self.positions_button = self._tool_button(pymodaq_icon(('target',), ARMED_COLOR), 'Pos.', '')
        self.history_button = self._tool_button(None, '', '')
        self.history_button.setCheckable(True)
        self._update_history_icon(False)
        self.settings_button = self._tool_button(None, 'Settings', '')
        self.settings_button.setCheckable(True)
        self.help_button = self._tool_button(pymodaq_icon(('help', 'help1'), 'gray'), '?', '')
        header.addWidget(self.close_button)
        header.addWidget(self.state_label)
        header.addStretch()
        header.addWidget(self.mode_label)
        header.addWidget(self.on_top_check)
        header.addWidget(self.positions_button)
        header.addWidget(self.history_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.help_button)
        layout.addLayout(header)

        self.top_container = QtWidgets.QWidget()        # for an application embedding the panel (set_top_widget)
        QtWidgets.QVBoxLayout(self.top_container).setContentsMargins(0, 0, 0, 2)
        self.top_container.setVisible(False)
        layout.addWidget(self.top_container)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(8)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(2)
        self.rows_widget = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.rows_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(1)
        self._band = QtWidgets.QFrame(self.rows_widget)          # light band behind the selected line
        self._band.setStyleSheet(f'background-color: {SELECTION_BAND}; border-radius: 3px;')
        self._band.hide()
        left.addWidget(self.rows_widget)

        self.empty_label = QtWidgets.QLabel('No actuator in the Dashboard (or all hidden: see the settings).')
        self.empty_label.setStyleSheet('color: gray;')
        left.addWidget(self.empty_label)

        self.detail_label = QtWidgets.QLabel('')
        self.detail_label.setTextFormat(Qt.RichText)
        left.addWidget(self.detail_label)

        self.message_label = QtWidgets.QLabel('')
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        left.addWidget(self.message_label)
        self.toast_space = QtWidgets.QWidget()          # line of the pressed keys display, when enabled
        self.toast_space.setFixedHeight(QtGui.QFontMetrics(self.font()).height() + 14)
        self.toast_space.setVisible(False)
        left.addWidget(self.toast_space)
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
        self.positions_button.clicked.connect(
            lambda: self.positions_requested.emit(self.positions_button.mapToGlobal(
                QtCore.QPoint(0, self.positions_button.height()))))
        self.help_button.clicked.connect(self._show_help_menu)
        for key, widget in (('close', self.close_button), ('on_top', self.on_top_check),
                            ('positions', self.positions_button), ('history', self.history_button),
                            ('settings', self.settings_button), ('help', self.help_button),
                            ('state', self.state_label), ('detail', self.detail_label)):
            self.set_tip(widget, *TIPS[key])

        self.key_toast = KeyToast(self)

        self._watchdog = QtCore.QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self.update_armed)
        self._watchdog.start()
        self.update_armed()

    # ------------------------------------------------------------------ tooltips and help
    def set_tip(self, widget: QtWidgets.QWidget, verbose: str, concise: str):
        """One-line tooltip of a widget, (verbose, concise) shown according to the tips mode"""
        self._tips[widget] = (verbose, concise)
        widget.setToolTip(tip_text(verbose, concise, self.tips_mode))

    def tip(self, verbose: str, concise: str) -> str:
        """Text of a tooltip in the current mode (for the widgets of an embedding application)"""
        return tip_text(verbose, concise, self.tips_mode)

    def set_tips_mode(self, mode: str):
        """Verbose or concise tooltips (the ? button), applied at once"""
        if mode not in (TIPS_VERBOSE, TIPS_CONCISE):
            mode = TIPS_VERBOSE
        changed = mode != self.tips_mode
        self.tips_mode = mode
        for widget, (verbose, concise) in list(self._tips.items()):
            try:
                widget.setToolTip(tip_text(verbose, concise, mode))
            except RuntimeError:               # deleted widget
                self._tips.pop(widget, None)
        self._apply_line_tips()
        if changed:
            self.tips_mode_changed.emit(mode)

    def _apply_line_tips(self):
        for line in self._lines:
            text = line.info.tooltip or tip_text(*line_tips(line.info.number, self._move_keys_label),
                                                 self.tips_mode)
            for label in line.labels:
                label.setToolTip(text)

    def help_menu(self) -> QtWidgets.QMenu:
        """Menu of the ? button: the full help, the tooltips mode"""
        menu = QtWidgets.QMenu(self)
        menu.addAction('Help: keys and mouse…', self.show_help)
        menu.addSeparator()
        group = (getattr(QtWidgets, 'QActionGroup', None) or QtGui.QActionGroup)(menu)
        for mode, text in ((TIPS_VERBOSE, 'Tooltips: verbose'), (TIPS_CONCISE, 'Tooltips: concise')):
            action = menu.addAction(text, lambda m=mode: self.set_tips_mode(m))
            action.setCheckable(True)
            action.setChecked(self.tips_mode == mode)
            group.addAction(action)
        return menu

    def _show_help_menu(self):
        menu = self.help_menu()
        pos = self.help_button.mapToGlobal(QtCore.QPoint(0, self.help_button.height()))
        menu.exec(pos) if hasattr(menu, 'exec') else menu.exec_(pos)
        self.setFocus(Qt.OtherFocusReason)

    def show_help(self):
        """The full help in a non-modal box (click the panel again to activate the keys)"""
        if self._help_box is None:
            self._help_box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, 'Keyboard Jog: help', '',
                                                   QtWidgets.QMessageBox.Close, self.window())
            self._help_box.setModal(False)
        self._help_box.setText(self.help_text)
        self._help_box.show()
        self._help_box.raise_()

    def set_key_toast_enabled(self, enabled: bool):
        """Pressed keys display: a line is kept free for it at the bottom of the lines"""
        self.toast_space.setVisible(enabled)
        if not enabled:
            self.key_toast.hide()

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        self.key_toast.place()

    @staticmethod
    def _tool_button(icon: Optional[QtGui.QIcon], text: str, tip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.NoFocus)     # clicking it must not take the focus from the panel
        if icon is not None:
            button.setIcon(icon)
        else:
            button.setText(text)
        return button

    def _colors(self) -> Tuple[str, str]:
        """(normal, dimmed) text colors from the palette (light and dark themes)"""
        palette = self.palette()
        text = palette.color(QtGui.QPalette.WindowText)
        back = palette.color(QtGui.QPalette.Window)
        mix = lambda a, b: int(a * 0.55 + b * 0.45)  # noqa: E731
        muted = QtGui.QColor(mix(text.red(), back.red()), mix(text.green(), back.green()),
                             mix(text.blue(), back.blue()))
        return text.name(), muted.name()

    # ------------------------------------------------------------------ settings / history containers
    def set_top_widget(self, widget: QtWidgets.QWidget):
        """A widget of the embedding application, between the header and the lines (it must refuse the focus)"""
        self.top_container.layout().addWidget(widget)
        self.top_container.setVisible(True)

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
        self.grid.removeWidget(self._band)
        self._band.hide()
        self._lines, self._line_of = [], {}
        for column in range(self.grid.columnCount()):
            self.grid.setColumnMinimumWidth(column, 0)
        rows = list(rows)
        columns, lines = grid_shape(len(rows))
        for column in range(1, columns):
            self.grid.setColumnMinimumWidth(column * COLUMNS_PER_BLOCK - 1, 12)   # gap between two columns
        for i, info in enumerate(rows):
            line = _Line(self.grid, i % lines, i // lines, info, self._value_font)
            self._lines.append(line)
            for name in info.actuators:
                self._line_of[name] = line
                self._show_value(name)
        self.empty_label.setVisible(not rows)
        self.detail_label.setVisible(bool(rows))
        self._apply_line_tips()
        self.set_selected(self._selected)

    def set_hint(self, move_keys_label: str):
        """Labels of the movement keys (line tooltips)"""
        self._move_keys_label = move_keys_label
        self._apply_line_tips()

    def row_names(self) -> List[str]:
        """The actuators of the lines, in the line order"""
        return [name for line in self._lines for name in line.info.actuators]

    def line_count(self) -> int:
        return len(self._lines)

    def line_position(self, index: int) -> Tuple[int, int]:
        """(line, column of groups) of the group of this index"""
        for line in self._lines:
            if line.info.index == index:
                row, base = line.grid_position
                return row, base // COLUMNS_PER_BLOCK
        return -1, -1

    def header_text(self, index: int) -> str:
        for line in self._lines:
            if line.info.index == index:
                return line.name.text()
        return ''

    def set_selected(self, index: int):
        self._selected = index
        self.grid.removeWidget(self._band)
        self._band.hide()
        for line in self._lines:
            line.selected = line.info.index == index
            if line.selected:
                row, base = line.grid_position
                self.grid.addWidget(self._band, row, base, 1, COLUMNS_PER_BLOCK - 1)
                self._band.show()
                self._band.lower()
        self._restyle()

    def selected_names(self) -> List[str]:
        return [name for line in self._lines if line.selected for name in line.info.actuators]

    def _restyle(self):
        normal, muted = self._colors()
        for line in self._lines:
            line.apply_style(self._busy, normal, muted, self._value_font, self._active)

    def set_active(self, name: str, active: bool):
        """Line of this actuator in green while it is active (e.g. a PID setpoint while its PID runs)"""
        if (name in self._active) == bool(active):
            return
        if active:
            self._active.add(name)
        else:
            self._active.discard(name)
        line = self._line_of.get(name)
        if line is not None:
            normal, muted = self._colors()
            line.apply_style(self._busy, normal, muted, self._value_font, self._active)

    def is_active(self, name: str) -> bool:
        return name in self._active

    def set_detail(self, items: Sequence[DetailItem]):
        """Detail line of the selected group: key caps, then step / mode / Δ of each actuator"""
        self._detail_plain = '   '.join(item.plain() for item in items)
        normal, muted = self._colors()
        parts = []
        for item in items:
            caps = '&nbsp;'.join(''.join(f"<span style='background-color:{muted}; color:white;'>&nbsp;"
                                         f"{html.escape(k)}&nbsp;</span>&nbsp;" for k in group)
                                 for group in item.keys)
            parts.append(f'{caps}{html.escape(item.text)}')
        self.detail_label.setText('&nbsp;&nbsp;&nbsp;'.join(parts))

    def detail_text(self) -> str:
        return self._detail_plain

    # ------------------------------------------------------------------ values
    def set_value(self, name: str, value: Optional[float]):
        self._values[name] = value
        self._show_value(name)

    def set_step(self, name: str, step: float):
        self._steps[name] = step
        self._show_value(name)

    def set_decimals(self, name: str, decimals: Optional[int]):
        """Digits shown after the decimal point (None: from the step)"""
        if self._decimals.get(name) != decimals:
            self._decimals[name] = decimals
            line = self._line_of.get(name)
            if line is not None and name in line.values:
                line.values[name].setMinimumWidth(0)      # fewer digits: the column may shrink
            self._show_value(name)

    def _show_value(self, name: str):
        line = self._line_of.get(name)
        if line is None or name in line.info.headless:
            return
        label = line.values[name]
        text = format_value(self._values.get(name), '', self._steps.get(name), self._decimals.get(name))
        label.setText(text)
        font = QtGui.QFont(self._value_font)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() + 1)                # room for the selected (larger) font
        width = QtGui.QFontMetrics(font).horizontalAdvance(text) + 8
        if width > label.minimumWidth():          # grows, never shrinks: the columns do not jump
            label.setMinimumWidth(width)

    def value_text(self, name: str) -> str:
        line = self._line_of.get(name)
        return line.values[name].text() if line is not None else ''

    def set_busy(self, name: str, busy: bool):
        """Value (or name of a headless actuator) highlighted while the actuator moves"""
        if (name in self._busy) == busy:
            return
        if busy:
            self._busy.add(name)
        else:
            self._busy.discard(name)
        line = self._line_of.get(name)
        if line is not None:
            normal, muted = self._colors()
            line.apply_style(self._busy, normal, muted, self._value_font, self._active)

    def is_busy_shown(self, name: str) -> bool:
        line = self._line_of.get(name)
        if line is None:
            return False
        label = line.name if name in line.info.headless else line.values[name]
        return line.is_busy_label(label)

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
        if child is self._band:
            for line in self._lines:
                if line.selected:
                    return line.info, ''
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
