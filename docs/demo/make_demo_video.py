"""Make the demo video of Keyboard Jog (silent MP4 with captions), reproducible after any change of the UI.

    pip install imageio-ffmpeg        # (or put it on the PYTHONPATH): provides the ffmpeg binary
    python docs/demo/make_demo_video.py [output.mp4]

PyMoDAQ >= 5.2 (experiment), pymodaq_plugins_mock needed. Everything runs offscreen (nothing shows on the screen):
the real Dashboard and the extension are driven with simulated mouse clicks and key presses; each frame is composed
from the windows (with a simple title bar), the open menus, a drawn mouse cursor and a caption band, and piped to
ffmpeg. The setups, history and positions go to a temporary folder.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ZOOM = 1.6                    # the windows are rendered at this scale: crisp and large in the video
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['QT_SCALE_FACTOR'] = str(ZOOM)
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_FONTDIR', os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts'))

from qtpy import QtCore, QtGui, QtWidgets  # noqa: E402

Qt = QtCore.Qt
OUT_W, OUT_H = 1920, 1080     # video size (pixels)
W, H = int(OUT_W / ZOOM), int(OUT_H / ZOOM)    # 'desktop' size in Qt logical coordinates
FPS = 20
TITLE_H = 26
EXPERIMENT = 'keyboard_jog_demo'
MOVES = (('Stage X', 'Y'), ('Stage Y', 'Y'), ('Focus Z', 'Y'))
BACKGROUND = ('#2b3a4a', '#16202a')
TEXT_FONT = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'   # captions, cards, title bars
REST = QtCore.QPointF(W * 0.42, H * 0.62)   # cursor out of the way, over the empty part of the Dashboard


class Recorder:
    """Real-time frames of the composed 'desktop', piped to ffmpeg"""

    def __init__(self, path: Path):
        import imageio_ffmpeg
        self.app = QtWidgets.QApplication.instance()
        self.windows = []                   # top-level widgets drawn, in z order (with a title bar)
        self.cursor = QtCore.QPointF(W * 0.55, H * 0.6)
        self.ring = None                    # (position, frames left) of a click
        self.caption = ''
        self.caption_frames = 0
        self.card = None                    # full-screen title card text
        self.frames = 0
        self._next = time.monotonic()
        self.ffmpeg = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
             '-s', f'{OUT_W}x{OUT_H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '24',
             '-preset', 'slow', '-movflags', '+faststart', str(path)], stdin=subprocess.PIPE)

    # ------------------------------------------------------------------ frames
    def frame(self):
        self._next += 1 / FPS
        while True:                          # real time: the actuators move while we wait
            self.app.processEvents()
            if time.monotonic() >= self._next:
                break
            time.sleep(0.002)
        image = QtGui.QImage(OUT_W, OUT_H, QtGui.QImage.Format_RGB888)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.scale(OUT_W / W, OUT_H / H)
        for widget, _ in self.windows[1:]:        # the extension: anchored to the right edge (it grows / shrinks)
            if widget.isVisible() and widget.x() != W - 8 - widget.width():
                widget.move(max(8, W - 8 - widget.width()), widget.y())
        gradient = QtGui.QLinearGradient(0, 0, 0, H)
        gradient.setColorAt(0, QtGui.QColor(BACKGROUND[0]))
        gradient.setColorAt(1, QtGui.QColor(BACKGROUND[1]))
        painter.fillRect(0, 0, W, H, gradient)
        if self.card is not None:
            self._draw_card(painter)
        else:
            for widget, title in self.windows:
                if widget.isVisible():
                    self._draw_window(painter, widget, title)
            for menu in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(menu, QtWidgets.QMenu) and menu.isVisible():
                    painter.drawPixmap(menu.pos(), menu.grab())
            self._draw_caption(painter)
            self._draw_cursor(painter)
        painter.end()
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        self.ffmpeg.stdin.write(bytes(ptr))
        self.frames += 1

    def hold(self, seconds: float):
        for _ in range(max(1, int(seconds * FPS))):
            self.frame()

    def close(self):
        self.ffmpeg.stdin.close()
        self.ffmpeg.wait()

    # ------------------------------------------------------------------ drawing
    def _draw_window(self, painter, widget, title):
        pos = widget.pos()
        bar = QtCore.QRectF(pos.x(), pos.y() - TITLE_H, widget.width(), TITLE_H)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor('#3c3f41'))
        painter.drawRoundedRect(bar.adjusted(0, 0, 0, 6), 6, 6)
        painter.setPen(QtGui.QColor('#d0d0d0'))
        font = QtGui.QFont(TEXT_FONT)
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(bar.adjusted(12, 0, -40, 0), Qt.AlignVCenter | Qt.AlignLeft, title)
        painter.drawText(bar.adjusted(0, 0, -14, 0), Qt.AlignVCenter | Qt.AlignRight, '✕')
        painter.drawPixmap(pos, widget.grab())

    def _draw_cursor(self, painter):
        if self.ring is not None:
            center, left = self.ring
            radius = 8 + (8 - left) * 3
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 90, int(30 * left)), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius, radius)
            self.ring = (center, left - 1) if left > 1 else None
        x, y = self.cursor.x(), self.cursor.y()
        arrow = QtGui.QPolygonF([QtCore.QPointF(x + dx, y + dy) for dx, dy in
                                 ((0, 0), (0, 22), (6, 17), (10, 26), (14, 24), (10, 15), (17, 15))])
        painter.setPen(QtGui.QPen(QtGui.QColor('black'), 1.5))
        painter.setBrush(QtGui.QColor('white'))
        painter.drawPolygon(arrow)

    def _draw_caption(self, painter):
        if not self.caption:
            return
        alpha = min(1.0, self.caption_frames / 6)       # fade in
        self.caption_frames += 1
        font = QtGui.QFont(TEXT_FONT)
        font.setPointSize(13)
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        width = metrics.horizontalAdvance(self.caption) + 40
        rect = QtCore.QRectF((W - width) / 2, H - 60, width, 38)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(15, 15, 25, int(215 * alpha)))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QtGui.QColor(255, 255, 255, int(255 * alpha)))
        painter.drawText(rect, Qt.AlignCenter, self.caption)

    def _draw_card(self, painter):
        title, lines = self.card
        font = QtGui.QFont(TEXT_FONT)
        font.setPointSize(28)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QtGui.QColor('white'))
        painter.drawText(QtCore.QRectF(0, H * 0.30, W, 60), Qt.AlignCenter, title)
        font.setPointSize(14)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QtGui.QColor('#c8d3dc'))
        for i, line in enumerate(lines):
            painter.drawText(QtCore.QRectF(0, H * 0.30 + 80 + 32 * i, W, 32), Qt.AlignCenter, line)

    # ------------------------------------------------------------------ actions
    def say(self, text: str):
        if text != self.caption:
            self.caption = text
            self.caption_frames = 0

    def move_to(self, target, seconds: float = 0.7):
        target = QtCore.QPointF(target)
        start = QtCore.QPointF(self.cursor)
        n = max(1, int(seconds * FPS))
        for i in range(1, n + 1):
            t = i / n
            t = t * t * (3 - 2 * t)                      # ease in / out
            self.cursor = start + (target - start) * t
            self.frame()

    def click_ring(self):
        self.ring = (QtCore.QPointF(self.cursor), 8)


def center_of(widget, rect: QtCore.QRect = None) -> QtCore.QPoint:
    rect = rect if rect is not None else widget.rect()
    return widget.mapToGlobal(rect.center())


def find_param(root, name):
    for child in root.children():
        if child.name() == name:
            return child
        found = find_param(child, name)
        if found is not None:
            return found
    return None


def key(panel, k, text='', release=True, modifiers=Qt.NoModifier):
    event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, k, modifiers, text)
    QtWidgets.QApplication.sendEvent(panel, event)
    if release:
        QtWidgets.QApplication.sendEvent(panel, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, k, modifiers, text))


def main(output: Path):
    from pymodaq_gui.qt_utils import mkQApp
    app = mkQApp('Keyboard Jog demo')  # noqa: F841
    import pymodaq_plugins_keyboardjog.extensions.keyboard_jog as kj
    from pymodaq.dashboard import DashBoard, load_dashboard_with_experiment
    from pymodaq_plugins_keyboardjog.tools.mock_config import write_mock_config

    folder = Path(tempfile.mkdtemp())
    kj.default_folder = lambda config=None: folder / 'setups'
    kj.is_azerty = lambda: False                         # QWERTY labels (W A S D) for an international video
    DashBoard.check_update = lambda self, show=True: False
    experiment = write_mock_config(EXPERIMENT, MOVES, overwrite=True)

    rec = Recorder(output)
    try:
        run(rec, kj, load_dashboard_with_experiment)
    finally:
        rec.close()
        for p in experiment.parent.glob(f'{EXPERIMENT}*'):
            try:
                p.unlink()
            except OSError:
                pass
    print(f'{output}: {rec.frames} frames, {rec.frames / FPS:.0f} s')


def run(rec: Recorder, kj, load_dashboard_with_experiment):
    from qtpy.QtTest import QTest

    rec.card = ('Keyboard Jog', ['A PyMoDAQ Dashboard extension', 'Move your actuators with the keyboard'])
    rec.hold(0.5)
    dashboard, _, _ = load_dashboard_with_experiment(EXPERIMENT)
    dash_win = dashboard.mainwindow
    dash_win.setGeometry(10, 10 + TITLE_H, 1030, 600)
    while not all(m.initialized_state for m in dashboard.actuators_modules) or len(dashboard.actuators_modules) < len(MOVES):
        rec.frame()
    for module in dashboard.actuators_modules:          # slower moves: they can be seen
        hw = module.settings.child(getattr(module, '_hw_settings_name', 'move_settings'))
        tau = find_param(hw, 'tau')
        if tau is not None:
            tau.setValue(250)
    rec.hold(2.5)
    rec.card = None
    rec.windows = [(dash_win, 'PyMoDAQ Dashboard')]

    rec.say('A PyMoDAQ Dashboard with 3 actuators (mock plugins)')
    rec.hold(2.5)

    # ---------------------------------------------------------------- open the extension from the menu
    rec.say('Open Keyboard Jog from the Extensions menu')
    menubar = dash_win.menuBar()
    menu = dashboard.get_menu('extensions')
    top = next((a for a in menubar.actions() if a.menu() is not None and menu.menuAction() in a.menu().actions()),
               menu.menuAction())                        # PyMoDAQ 5.3: Tools > Extensions
    rec.move_to(center_of(menubar, menubar.actionGeometry(top)))
    rec.click_ring()
    if top is not menu.menuAction():
        tools = top.menu()
        tools.popup(menubar.mapToGlobal(menubar.actionGeometry(top).bottomLeft()))
        rec.hold(0.4)
        rec.move_to(center_of(tools, tools.actionGeometry(menu.menuAction())), 0.5)
        tools.setActiveAction(menu.menuAction())
        menu.popup(tools.mapToGlobal(tools.actionGeometry(menu.menuAction()).topRight()))
    else:
        tools = None
        menu.popup(menubar.mapToGlobal(menubar.actionGeometry(top).bottomLeft()))
    rec.hold(0.5)
    action = next(a for a in menu.actions() if 'keyboard' in a.text().lower().replace(' ', ''))
    rec.move_to(center_of(menu, menu.actionGeometry(action)), 0.6)
    menu.setActiveAction(action)
    rec.hold(0.4)
    rec.click_ring()
    menu.hide()
    if tools is not None:
        tools.hide()
    action.trigger()
    ext = dashboard.extensions[next(e for e in dashboard.extensions if 'KEYBOARD' in str(e).upper())]
    win = ext.mainwindow
    win.move(W - 10 - win.width(), 120 + TITLE_H)
    dash_win.activateWindow()                            # the focus is elsewhere: red
    rec.windows.append((win, 'Keyboard Jog'))
    rec.hold(1.0)
    rec.say('A tiny window, always on top. Red border: the keys are ignored')
    rec.hold(3.0)

    # ---------------------------------------------------------------- focus
    rec.say('Click it: green border, the keyboard now moves the actuators')
    rec.move_to(center_of(ext.panel.state_label))
    rec.click_ring()
    win.activateWindow()
    QTest.mouseClick(ext.panel, Qt.LeftButton, Qt.NoModifier, ext.panel.state_label.geometry().center())
    rec.hold(2.5)
    ext.settings.child('general', 'show_keys').setValue(True)       # pressed keys display (demo, teaching)

    # ---------------------------------------------------------------- zero configuration
    rec.say('No setup needed: every actuator has a number, the first one is selected')
    rec.hold(2.5)
    rec.move_to(REST, 0.5)   # mouse out of the way
    rec.say('D / A move it: one key press = one step')
    for _ in range(3):
        key(ext.panel, Qt.Key_D, 'd')
        rec.hold(0.7)
    key(ext.panel, Qt.Key_A, 'a')
    rec.hold(1.2)
    rec.say('The number keys select another actuator')
    key(ext.panel, Qt.Key_3, '3')
    rec.hold(0.8)
    key(ext.panel, Qt.Key_D, 'd')
    rec.hold(0.8)
    key(ext.panel, Qt.Key_D, 'd')
    rec.hold(1.2)
    key(ext.panel, Qt.Key_1, '1')
    rec.hold(0.8)

    # ---------------------------------------------------------------- pair
    rec.say('Right-click: pair two actuators (X / Y of a stage)')
    line = ext.panel._line_of['Stage X']
    rec.move_to(center_of(line.name))
    rec.click_ring()
    group_menu = ext.group_menu(line.info.index)
    group_menu.popup(center_of(line.name) + QtCore.QPoint(6, 6))
    rec.hold(0.5)
    pair_action = group_menu.actions()[0]
    rec.move_to(center_of(group_menu, group_menu.actionGeometry(pair_action)), 0.5)
    group_menu.setActiveAction(pair_action)
    sub = pair_action.menu()
    sub.popup(group_menu.mapToGlobal(group_menu.actionGeometry(pair_action).topRight()))
    rec.hold(0.4)
    target = next(a for a in sub.actions() if a.text() == 'Stage Y')
    rec.move_to(center_of(sub, sub.actionGeometry(target)), 0.5)
    sub.setActiveAction(target)
    rec.hold(0.4)
    rec.click_ring()
    sub.hide()
    group_menu.hide()
    ext.pair_actuators('Stage X', 'Stage Y', name='Sample stage')
    rec.hold(1.0)
    rec.say('One number, one line: A / D move X, W / S move Y')
    rec.move_to(REST, 0.4)
    for k, t in ((Qt.Key_D, 'd'), (Qt.Key_D, 'd'), (Qt.Key_W, 'w'), (Qt.Key_W, 'w'), (Qt.Key_A, 'a'),
                 (Qt.Key_S, 's')):
        key(ext.panel, k, t)
        rec.hold(0.75)
    rec.say('+ / − : step × 10 / ÷ 10')
    key(ext.panel, Qt.Key_Plus, '+')
    rec.hold(1.4)
    key(ext.panel, Qt.Key_D, 'd')
    rec.hold(1.2)
    key(ext.panel, Qt.Key_Minus, '-')
    rec.hold(1.4)

    # ---------------------------------------------------------------- continuous mode
    rec.say('Settings: continuous mode, steps, keys, pairs, saved setups…')
    rec.move_to(center_of(ext.panel.settings_button))
    rec.click_ring()
    ext.panel.settings_button.click()
    rec.hold(0.6)
    item = next(iter(ext.settings.child('general', 'all_continuous').items))
    rect = ext.tree.visualItemRect(item)
    rec.move_to(ext.tree.viewport().mapToGlobal(QtCore.QPoint(rect.right() - 40, rect.center().y())))
    rec.click_ring()
    ext.settings.child('general', 'all_continuous').setValue(True)
    rec.hold(1.2)
    rec.move_to(center_of(ext.panel.settings_button))
    rec.click_ring()
    ext.panel.settings_button.click()
    win.activateWindow()
    ext.panel.setFocus(Qt.MouseFocusReason)
    rec.hold(0.8)
    rec.move_to(REST, 0.4)
    rec.say('Continuous: steps repeat while the key is held, and stop when released')
    key(ext.panel, Qt.Key_D, 'd', release=False)
    rec.hold(2.5)
    QtWidgets.QApplication.sendEvent(ext.panel, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, Qt.Key_D, Qt.NoModifier, 'd'))
    rec.hold(1.2)
    rec.say('Shift: × 10 while held, Ctrl: ÷ 10')
    key(ext.panel, Qt.Key_Shift, '', release=False, modifiers=Qt.ShiftModifier)
    key(ext.panel, Qt.Key_W, 'W', release=False, modifiers=Qt.ShiftModifier)
    rec.hold(2.0)
    QtWidgets.QApplication.sendEvent(ext.panel, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, Qt.Key_W,
                                                                Qt.ShiftModifier, 'W'))
    QtWidgets.QApplication.sendEvent(ext.panel, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, Qt.Key_Shift,
                                                                Qt.NoModifier, ''))
    rec.hold(1.5)

    # ---------------------------------------------------------------- safety
    rec.say('Click elsewhere: red border, keys ignored, the moves stop (safety)')
    rec.move_to(QtCore.QPointF(520, 520))
    rec.click_ring()
    dash_win.activateWindow()
    rec.hold(1.0)
    for _ in range(3):
        key(ext.panel, Qt.Key_D, 'd')                    # ignored
        rec.hold(0.5)
    rec.hold(1.0)
    rec.say('Same values in the Dashboard: everything goes through its DAQ_Move modules')
    rec.hold(3.0)
    rec.move_to(center_of(ext.panel.state_label))
    rec.click_ring()
    win.activateWindow()
    QTest.mouseClick(ext.panel, Qt.LeftButton, Qt.NoModifier, ext.panel.state_label.geometry().center())
    rec.hold(1.0)

    # ---------------------------------------------------------------- history and positions
    rec.say('History: every end of move of the selected group')
    rec.move_to(center_of(ext.panel.history_button))
    rec.click_ring()
    ext.panel.history_button.click()
    win.activateWindow()
    ext.panel.setFocus(Qt.MouseFocusReason)
    rec.hold(1.0)
    ext.settings.child('general', 'all_continuous').setValue(False)
    for k, t in ((Qt.Key_D, 'd'), (Qt.Key_W, 'w'), (Qt.Key_D, 'd')):
        key(ext.panel, k, t)
        rec.hold(0.8)
    rec.say('Save the current position under a name')
    rec.move_to(center_of(ext.panel.positions_button))
    rec.click_ring()
    positions_menu = ext.positions_menu()
    positions_menu.popup(ext.panel.positions_button.mapToGlobal(
        QtCore.QPoint(0, ext.panel.positions_button.height())))
    rec.hold(0.5)
    save = next(a for a in positions_menu.actions() if a.text().startswith('Save current'))
    rec.move_to(center_of(positions_menu, positions_menu.actionGeometry(save)), 0.5)
    positions_menu.setActiveAction(save)
    rec.hold(0.4)
    rec.click_ring()
    positions_menu.hide()
    ext.save_position('Aligned')
    rec.hold(1.5)
    rec.say('…move away…')
    rec.move_to(REST, 0.4)
    for k, t in ((Qt.Key_D, 'd'), (Qt.Key_D, 'd'), (Qt.Key_S, 's'), (Qt.Key_S, 's'), (Qt.Key_S, 's')):
        key(ext.panel, k, t)
        rec.hold(0.75)
    rec.say('Click its star (or use the menu): back to it')
    plot = ext.history_plot.plot
    star = ext.positions.get(['Stage X', 'Stage Y'], 'Aligned').values
    scene = plot.getPlotItem().getViewBox().mapViewToScene(QtCore.QPointF(*star))
    rec.move_to(plot.mapToGlobal(plot.mapFromScene(scene)))
    rec.click_ring()
    ext._ask = lambda title, text: True                  # the confirmation dialog: accepted
    ext.go_to_position('Aligned')
    rec.hold(3.0)

    # ---------------------------------------------------------------- end
    rec.say('Close: the red cross')
    rec.move_to(center_of(ext.panel.close_button))
    rec.click_ring()
    rec.hold(0.3)
    ext.panel.close_button.click()
    rec.hold(1.5)
    rec.say('')
    rec.card = ('Keyboard Jog', ['pip install pymodaq_plugins_keyboardjog',
                                 'PyMoDAQ 5.1 and 5.3 · open source · github.com/PyMoDAQ'])
    rec.hold(4.0)
    try:
        dashboard.quit_fun()
    except Exception:
        pass


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('keyboard_jog_demo.mp4'))
    os._exit(0)
