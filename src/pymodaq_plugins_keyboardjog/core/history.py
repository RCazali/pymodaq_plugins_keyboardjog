"""End-of-move history of the groups (ported from the Alignment tab of LaserControl).

For each group of actuators (a pair: horizontal, vertical; or one actuator) a series of points ``[time, v1, (v2)]``
is recorded each time one of its actuators finishes a move, whatever moved it (this window, the Dashboard, a
scan...). The point before the move is added too when it is not already the last one, so that the path is complete.
The series are kept in a JSON file, at most ``max_points`` per group.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from pymodaq_utils.logger import set_logger, get_module_name

logger = set_logger(get_module_name(__file__))

HISTORY_MAX = 2000
HISTORY_FILE = 'history.json'


def series_key(actuators: Sequence[str]) -> str:
    return '|'.join(actuators)


def same_point(a: Sequence[float], b: Sequence[float]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


class MoveHistory:

    def __init__(self, path: Optional[Path] = None, max_points: int = HISTORY_MAX):
        self.path = Path(path) if path is not None else None
        self.max_points = max_points
        self.series: Dict[str, List[List[float]]] = {}
        self.settled: Dict[str, float] = {}          # last end-of-move value of each actuator
        self.load()

    def points(self, actuators: Sequence[str]) -> List[List[float]]:
        return self.series.get(series_key(actuators), [])

    def record(self, actuator: str, value: float, groups: Iterable[Sequence[str]], now: float = None) -> Set[str]:
        """End of a move of ``actuator`` at ``value``: add a point to every group containing it. Returns the keys of
        the series that changed."""
        before_all = dict(self.settled)
        self.settled[actuator] = float(value)
        now = time.time() if now is None else now
        changed = set()
        for actuators in groups:
            actuators = list(actuators)
            key = series_key(actuators)
            if actuator not in actuators or key in changed:
                continue
            after = [self.settled.get(a) for a in actuators]
            if any(v is None for v in after):
                continue
            before = [before_all.get(a) for a in actuators]
            series = self.series.setdefault(key, [])
            if not any(v is None for v in before) and (not series or not same_point(series[-1][1:], before)) \
                    and not same_point(before, after):
                series.append([now, *before])
            if not series or not same_point(series[-1][1:], after):
                series.append([now, *after])
                if len(series) > self.max_points:
                    del series[:len(series) - self.max_points]
                changed.add(key)
        return changed

    def set_settled(self, actuator: str, value: float):
        """Known value of an actuator that did not move yet (e.g. read at startup): start of its first path"""
        self.settled.setdefault(actuator, float(value))

    def clear(self, actuators: Sequence[str]) -> int:
        return len(self.series.pop(series_key(actuators), []))

    # ------------------------------------------------------------------ file
    def load(self):
        if self.path is None or not self.path.is_file():
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f).get('series', {})
            for key, points in raw.items():
                clean = [[float(x) for x in p] for p in points if isinstance(p, list) and len(p) >= 2]
                if clean:
                    self.series[str(key)] = clean[-self.max_points:]
        except Exception as e:
            logger.warning(f'history not read ({self.path}): {e}')

    def save(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'version': 1, 'series': self.series}, f)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f'history not saved ({self.path}): {e}')
