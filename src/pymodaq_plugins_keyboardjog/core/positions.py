"""Named positions of the groups ("HA", "pump max"...), to go back to them later.

A position belongs to a group: the actuators moved by its keys (horizontal, vertical), identified by their names, as
the history. The positions are kept in a JSON file of their own (``positions.json``), independent of the setups, so
that a position survives a change of setup.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pymodaq_utils.logger import set_logger, get_module_name

from .history import series_key

logger = set_logger(get_module_name(__file__))

POSITIONS_FILE = 'positions.json'


@dataclass
class SavedPosition:
    name: str
    values: List[float]
    time: float = 0.0


class PositionStore:

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else None
        self.positions: Dict[str, List[SavedPosition]] = {}
        self.load()

    def list(self, actuators: Sequence[str]) -> List[SavedPosition]:
        return list(self.positions.get(series_key(actuators), []))

    def names(self, actuators: Sequence[str]) -> List[str]:
        return [p.name for p in self.list(actuators)]

    def get(self, actuators: Sequence[str], name: str) -> Optional[SavedPosition]:
        return next((p for p in self.list(actuators) if p.name == name), None)

    def save(self, actuators: Sequence[str], name: str, values: Sequence[float], now: float = None) -> SavedPosition:
        """Save (or replace) the position of this name; values in the order of the actuators"""
        name = name.strip()
        if not name:
            raise ValueError('a position needs a name')
        if len(values) != len(actuators) or any(v is None for v in values):
            raise ValueError('the position of every actuator must be known')
        position = SavedPosition(name, [float(v) for v in values], time.time() if now is None else now)
        positions = [p for p in self.positions.get(series_key(actuators), []) if p.name != name]
        self.positions[series_key(actuators)] = positions + [position]
        self.write()
        return position

    def delete(self, actuators: Sequence[str], name: str):
        key = series_key(actuators)
        self.positions[key] = [p for p in self.positions.get(key, []) if p.name != name]
        if not self.positions[key]:
            del self.positions[key]
        self.write()

    # ------------------------------------------------------------------ file
    def load(self):
        if self.path is None or not self.path.is_file():
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f).get('positions', {})
            for key, items in raw.items():
                clean = []
                for item in items:
                    try:
                        clean.append(SavedPosition(str(item['name']), [float(v) for v in item['values']],
                                                   float(item.get('time', 0.0))))
                    except (KeyError, TypeError, ValueError):
                        continue
                if clean:
                    self.positions[str(key)] = clean
        except Exception as e:
            logger.warning(f'positions not read ({self.path}): {e}')

    def write(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            data = {key: [{'name': p.name, 'values': p.values, 'time': p.time} for p in items]
                    for key, items in self.positions.items()}
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'version': 1, 'positions': data}, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f'positions not saved ({self.path}): {e}')
