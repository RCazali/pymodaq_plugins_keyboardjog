"""History plot of the selected group (ported from the Alignment tab of LaserControl).

A pair is drawn in 2D (horizontal actuator on x, vertical on y), a single actuator along its own axis. The points go
from grey (old) to yellow (recent), the circled point is the last end of move, the cross the live position. Hovering
a point shows its values and time; clicking it asks to go back there, right-clicking it saves it as a named
position. The saved positions of the group are drawn as named stars: click one to go there.
"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtWidgets

HIST_BG = '#1e1e2e'
HIST_STOPS = np.array([[112, 118, 146], [137, 180, 250], [249, 226, 175]], dtype=float)
HIST_MARKER = '#f38ba8'
MARK_COLOR = '#a6e3a1'


def _history_colors(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 3))
    t = np.linspace(0.0, 1.0, n) if n > 1 else np.ones(1)
    seg = np.clip(t * (len(HIST_STOPS) - 1), 0, len(HIST_STOPS) - 1 - 1e-9)
    i = seg.astype(int)
    f = (seg - i)[:, None]
    return HIST_STOPS[i] * (1 - f) + HIST_STOPS[i + 1] * f


class HistoryPlot(QtWidgets.QWidget):
    point_clicked = QtCore.Signal(int)
    point_save_requested = QtCore.Signal(int)     # right-click on a point
    mark_clicked = QtCore.Signal(str)             # click on a saved position
    clear_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self._points: list = []
        self._marks: list = []                    # [(name, values)]
        self._mark_labels: list = []
        self._live: Optional[list] = None
        self._user_view = False          # the user zoomed / panned: stop following the data
        self._dims = 0
        self._orient: Optional[str] = None
        self._decimals = [4, 4]
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(2, 0, 2, 0)
        self.title = QtWidgets.QLabel('History')
        self.title.setStyleSheet('font-weight: bold;')
        bar.addWidget(self.title)
        self.count = QtWidgets.QLabel('')
        self.count.setStyleSheet('color: gray;')
        bar.addWidget(self.count)
        bar.addStretch()
        self.fit_button = QtWidgets.QToolButton()
        self.fit_button.setText('⤢')
        self.fit_button.setToolTip('Fit the whole history')
        self.clear_button = QtWidgets.QToolButton()
        self.clear_button.setText('🗑')
        self.clear_button.setToolTip('Clear the history of this group')
        for button in (self.fit_button, self.clear_button):
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setAutoRaise(True)
            bar.addWidget(button)
        self.fit_button.clicked.connect(self.fit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        layout.addLayout(bar)

        self.plot = pg.PlotWidget(background=HIST_BG)
        self.plot.setFocusPolicy(QtCore.Qt.NoFocus)
        self.plot.setMinimumHeight(140)
        item = self.plot.getPlotItem()
        item.hideButtons()
        item.showGrid(x=True, y=True, alpha=0.2)
        for name in ('left', 'bottom'):
            try:
                item.getAxis(name).enableAutoSIPrefix(False)
            except Exception:
                pass
        self._line = pg.PlotDataItem(pen=pg.mkPen((166, 173, 200, 70), width=1))
        self.plot.addItem(self._line)
        try:
            self._scatter = pg.ScatterPlotItem(pen=None, hoverable=True, hoverPen=pg.mkPen('w', width=1.5))
        except TypeError:
            self._scatter = pg.ScatterPlotItem(pen=None)
        self._scatter.sigClicked.connect(self._on_points_clicked)
        self.plot.addItem(self._scatter)
        self._last = pg.ScatterPlotItem(size=13, symbol='o', brush=None, pen=pg.mkPen((249, 226, 175), width=1.5))
        self.plot.addItem(self._last)
        self._marks_item = pg.ScatterPlotItem(size=15, symbol='star', pen=pg.mkPen('#1e1e2e', width=1),
                                              brush=pg.mkBrush(MARK_COLOR))
        self._marks_item.sigClicked.connect(self._on_marks_clicked)
        self.plot.addItem(self._marks_item)
        self._cursor = pg.ScatterPlotItem(size=16, symbol='+', pen=pg.mkPen(HIST_MARKER, width=2),
                                          brush=pg.mkBrush(HIST_MARKER))
        self.plot.addItem(self._cursor)
        self._empty = pg.TextItem('', color='#7f849c', anchor=(0.5, 1.5))
        self.plot.addItem(self._empty)
        item.getViewBox().sigRangeChangedManually.connect(self._on_manual_range)
        layout.addWidget(self.plot, stretch=1)

    def _on_manual_range(self, *args):
        self._user_view = True

    def set_group(self, name: str, orient: Optional[str], labels: Sequence[str], units: Sequence[str],
                  decimals: Sequence[int], color: str = ''):
        """orient: '2d' (pair), 'h' (one horizontal actuator), 'v' (one vertical actuator), None (nothing)"""
        self._orient = orient
        self._dims = len(labels) if orient else 0
        self._decimals = list(decimals) + [4, 4]
        mark = f"<span style='color:{color};'>■</span> " if color else ''
        self.title.setText(f'{mark}History · {name}')
        item = self.plot.getPlotItem()
        show_x = orient in ('2d', 'h')
        show_y = orient in ('2d', 'v')
        item.showAxis('bottom', show_x)
        item.showAxis('left', show_y)
        item.getViewBox().setMouseEnabled(x=show_x, y=show_y)
        if orient == 'h':
            item.setLabel('bottom', labels[0], units=units[0])
        elif orient == 'v':
            item.setLabel('left', labels[0], units=units[0])
        elif orient == '2d':
            item.setLabel('bottom', labels[0], units=units[0])
            item.setLabel('left', labels[1], units=units[1])

    def point_count(self) -> int:
        return len(self._points)

    def mark_names(self) -> List[str]:
        return [name for name, _ in self._marks]

    def set_marks(self, marks: Sequence[tuple]):
        """Saved positions of the group: [(name, values)], drawn as named stars"""
        for label in self._mark_labels:
            self.plot.removeItem(label)
        self._mark_labels = []
        self._marks = [(name, list(values)) for name, values in marks
                       if self._dims and len(values) == self._dims]
        if not self._marks:
            self._marks_item.setData([], [])
            return
        xs, ys = self._xy([values for _, values in self._marks])
        self._marks_item.setData(x=xs, y=ys, data=[name for name, _ in self._marks])
        for (name, _), x, y in zip(self._marks, xs, ys):
            label = pg.TextItem(name, color=MARK_COLOR, anchor=(0, 1.2))
            label.setPos(float(x), float(y))
            self.plot.addItem(label)
            self._mark_labels.append(label)

    def set_points(self, points: List[list], live: Optional[list]):
        self._points = points
        n = len(points)
        self.count.setText(f"{n} move{'s' if n != 1 else ''}" if self._dims else '')
        if self._dims == 0 or n == 0:
            self._line.setData([], [])
            self._scatter.setData([], [])
            self._last.setData([], [])
            self._empty.setText('no actuator' if self._dims == 0 else 'no move recorded')
            x0 = y0 = 0.0
            if live and self._dims and all(v is not None for v in live):
                xs, ys = self._xy([live])
                x0, y0 = float(xs[0]), float(ys[0])
            self._empty.setPos(x0, y0)
            self._empty.setVisible(True)
        else:
            self._empty.setVisible(False)
            xs, ys = self._xy([p[1:] for p in points])
            rgb = _history_colors(n)
            alpha = np.linspace(150, 255, n) if n > 1 else np.full(1, 255.0)
            brushes = [pg.mkBrush(int(r), int(g), int(b), int(a)) for (r, g, b), a in zip(rgb, alpha)]
            sizes = np.linspace(5, 9, n) if n > 1 else np.full(1, 9.0)
            kwargs = dict(x=xs, y=ys, brush=brushes, size=sizes, data=list(range(n)))
            try:
                self._scatter.setData(tip=self._tip, **kwargs)
            except TypeError:
                self._scatter.setData(**kwargs)
            if self._orient == '2d':
                self._line.setData(xs, ys)
            else:
                self._line.setData([], [])
            self._last.setData([xs[-1]], [ys[-1]])
        self.update_live(live)
        if not self._user_view:
            self.fit()

    def update_live(self, live: Optional[list]):
        self._live = list(live) if live else None
        if not live or self._dims == 0 or any(v is None for v in live):
            self._cursor.setData([], [])
            return
        xs, ys = self._xy([live])
        self._cursor.setData(xs, ys)
        if not self._user_view:        # follow the live position when it leaves the view
            (x0, x1), (y0, y1) = self.plot.getPlotItem().getViewBox().viewRange()
            if not (x0 <= float(xs[0]) <= x1 and y0 <= float(ys[0]) <= y1):
                self.fit()

    @staticmethod
    def _span(values) -> tuple:
        """Range of values, never degenerate (a single point gets ±1 % of its value, at least ±1)"""
        lo, hi = float(np.min(values)), float(np.max(values))
        if hi - lo < 1e-12:
            half = max(1.0, abs(lo) * 0.01)
            return lo - half, hi + half
        pad = 0.08 * (hi - lo)
        return lo - pad, hi + pad

    def fit(self):
        item = self.plot.getPlotItem()
        item.disableAutoRange()
        points = [p[1:] for p in self._points] + [values for _, values in self._marks]
        if self._live and self._dims and all(v is not None for v in self._live):
            points.append(self._live)
        if not points or self._dims == 0:
            item.setXRange(-1, 1, padding=0)
            item.setYRange(-1, 1, padding=0)
            self._user_view = False
            return
        xs, ys = self._xy(points)
        if self._orient in ('h', '2d'):
            item.setXRange(*self._span(xs), padding=0)
        else:
            item.setXRange(-1, 1, padding=0)
        if self._orient in ('v', '2d'):
            item.setYRange(*self._span(ys), padding=0)
        else:
            item.setYRange(-1, 1, padding=0)
        self._user_view = False

    def _xy(self, values):
        a = np.array([[float(x) for x in v] for v in values], dtype=float)
        zero = np.zeros(len(a))
        if self._orient == '2d':
            return a[:, 0], a[:, 1]
        if self._orient == 'v':
            return zero, a[:, 0]
        return a[:, 0], zero

    def _tip(self, x=None, y=None, data=None, **_):
        try:
            point = self._points[int(data)]
        except Exception:
            return ''
        values = '  '.join(f'{v:.{d}f}' for v, d in zip(point[1:], self._decimals))
        when = time.strftime('%d/%m %H:%M:%S', time.localtime(point[0])) if point[0] else ''
        return f'#{int(data)}   {values}\n{when}\nclick: go back here, right-click: save as a position'

    @staticmethod
    def _is_right_click(args) -> bool:
        event = args[0] if args else None          # pyqtgraph >= 0.12 passes the mouse event
        try:
            return event is not None and event.button() == QtCore.Qt.RightButton
        except Exception:
            return False

    def _on_points_clicked(self, _item, points, *args):
        if len(points):
            index = points[-1].data()
            if index is not None:
                if self._is_right_click(args):
                    self.point_save_requested.emit(int(index))
                else:
                    self.point_clicked.emit(int(index))

    def _on_marks_clicked(self, _item, points, *args):
        if len(points) and points[-1].data():
            self.mark_clicked.emit(str(points[-1].data()))
