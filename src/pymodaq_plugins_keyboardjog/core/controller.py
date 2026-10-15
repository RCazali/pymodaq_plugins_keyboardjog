"""Motion controller: applies the move actions to the actuators.

Rules (safety, see the specification):

* keyboard moves are relative steps (``move_rel``); the only absolute move is the explicit "go back" to a point of
  the history, after confirmation (``move_to``);
* **no move is ever queued**: for a given actuator the next move is sent only once the previous one is done
  (move-done signal), and never while the actuator is moved by something else; a request arriving while the
  actuator is busy is dropped;
* each actuator is in step mode (one press = one step) or in continuous mode (steps repeated while the action is
  held, each one sent when the previous one is done, after an optional minimum interval, as the alignment jog of
  LaserControl);
* release: the repetition stops at once (the step in progress finishes);
* ``release_all`` (focus lost) forgets every held action and can stop the actuators moved by this extension.

A move whose move-done never arrives is forgotten after ``move_timeout_s`` (a warning is logged) so that one lost
signal does not lock the actuator forever.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from qtpy import QtCore

from pymodaq_utils.logger import set_logger, get_module_name

from .actions import InputSource, MoveAction
from .model import DEFAULT_STEP
from .ports import ActuatorPort

logger = set_logger(get_module_name(__file__))

TICK_MS = 10


@dataclass
class AxisState:
    pending: bool = False             # a move sent by this extension is not done yet
    sent_at: float = 0.0
    done_at: float = float('-inf')
    held: List[int] = field(default_factory=list)  # held directions, the last one wins


class MotionController(QtCore.QObject):
    step_changed = QtCore.Signal(str, float)
    message = QtCore.Signal(str)
    move_started = QtCore.Signal(str)              # a move was sent by this extension
    move_finished = QtCore.Signal(str, object)     # move done (any origin) with the reached value (None: unknown)

    def __init__(self, clock: Callable[[], float] = time.monotonic, parent: QtCore.QObject = None):
        super().__init__(parent)
        self._clock = clock
        self.ports: Dict[str, ActuatorPort] = {}
        self.steps: Dict[str, float] = {}
        self._continuous = frozenset()
        self.min_interval_s = 0.0
        self.move_timeout_s = 10.0
        self.multiplier = 1.0
        self._states: Dict[str, AxisState] = {}
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)

    # ------------------------------------------------------------------ configuration
    def connect_source(self, source: InputSource):
        source.move_pressed.connect(self.press)
        source.move_released.connect(self.release)
        source.multiplier_changed.connect(self.set_multiplier)
        source.reset_requested.connect(self.release_all)

    def set_ports(self, ports: Dict[str, ActuatorPort]):
        """New set of actuators: everything held is released, the steps of the known actuators are kept"""
        self.release_all(stop=False)
        self.ports = dict(ports)
        self._states = {name: AxisState() for name in self.ports}
        for name, port in self.ports.items():
            port.on_done = lambda value, n=name: self.on_move_done(n, value)

    @property
    def continuous(self) -> frozenset:
        """The actuators in continuous mode (the others are in step mode)"""
        return self._continuous

    @continuous.setter
    def continuous(self, names: Iterable[str]):
        names = frozenset(names)
        for name in names ^ self._continuous:          # mode changed: what is held is released
            state = self._states.get(name)
            if state is not None:
                state.held.clear()
        self._continuous = names

    def is_continuous(self, name: str) -> bool:
        return name in self._continuous

    def step(self, name: str) -> float:
        return float(self.steps.get(name, DEFAULT_STEP))

    def set_step(self, name: str, value: float):
        value = abs(float(value))
        if value > 0 and value != self.steps.get(name):
            self.steps[name] = value
            self.step_changed.emit(name, value)

    def scale_steps(self, sign: int, factor: float, names: Iterable[str]):
        """Multiply (sign > 0) or divide (sign < 0) the step of the given actuators by factor"""
        factor = float(factor)
        if factor <= 1:
            return
        for name in names:
            self.set_step(name, self.step(name) * (factor if sign > 0 else 1.0 / factor))

    def set_multiplier(self, value: float):
        self.multiplier = float(value)

    # ------------------------------------------------------------------ actions
    def press(self, action: MoveAction):
        state = self._states.get(action.actuator)
        if state is None:
            return
        if action.direction in state.held:
            state.held.remove(action.direction)
        state.held.append(action.direction)
        continuous = self.is_continuous(action.actuator)
        self._try_step(action.actuator, action.direction, self.multiplier if continuous else 1.0, report=True)
        if continuous:
            self._timer.start()

    def release(self, action: MoveAction):
        state = self._states.get(action.actuator)
        if state is not None and action.direction in state.held:
            state.held.remove(action.direction)

    def release_all(self, stop: bool = False):
        """Forget every held action; with ``stop``, stop the actuators this extension is moving"""
        for name, state in self._states.items():
            state.held.clear()
            if stop and state.pending:
                port = self.ports.get(name)
                try:
                    port.stop()
                    logger.info(f'{name}: stopped (keyboard released)')
                except Exception as e:
                    logger.warning(f'{name}: stop failed: {e}')

    def is_busy(self, name: str) -> bool:
        state = self._states.get(name)
        return bool(state is not None and state.pending)

    def is_held(self, name: str) -> bool:
        state = self._states.get(name)
        return bool(state is not None and state.held)

    def move_to(self, name: str, value: float) -> bool:
        """Absolute move (go back to a point of the history), with the same rules as a step"""
        return self._send(name, lambda port: port.move_abs(float(value)), f'move_abs({value:g})', report=True)

    # ------------------------------------------------------------------ motion
    def on_move_done(self, name: str, value: Optional[float] = None):
        state = self._states.get(name)
        if state is None:
            return
        if state.pending:
            state.pending = False
            state.done_at = self._clock()
        self.move_finished.emit(name, value)
        if self.is_continuous(name) and state.held:
            self.tick()

    def tick(self):
        now = self._clock()
        active = False
        for name, state in self._states.items():
            if state.pending and now - state.sent_at > self.move_timeout_s:
                state.pending = False
                state.done_at = now
                msg = f'{name}: no move-done after {self.move_timeout_s:g} s, actuator released'
                logger.warning(msg)
                self.message.emit(msg)
                self.move_finished.emit(name, None)
            if (self.is_continuous(name) and state.held and not state.pending
                    and now - state.done_at >= self.min_interval_s):
                self._try_step(name, state.held[-1], self.multiplier)
            active = active or state.pending or bool(state.held)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _try_step(self, name: str, direction: int, multiplier: float, report: bool = False) -> bool:
        delta = direction * self.step(name) * multiplier
        return self._send(name, lambda port: port.move_rel(delta), f'move_rel({delta:g})', report)

    def _send(self, name: str, move: Callable[[ActuatorPort], None], what: str, report: bool) -> bool:
        port = self.ports.get(name)
        state = self._states.get(name)
        if port is None or state is None:
            return False
        if state.pending:
            if report:
                self.message.emit(f'{name} is still moving: key ignored')
            return False
        if not port.is_initialized():
            if report:
                self.message.emit(f'{name} is not initialized')
            return False
        if port.is_moving():
            if report:
                self.message.emit(f'{name} is moved by something else: key ignored')
            return False
        try:
            started = move(port)
        except Exception as e:
            logger.warning(f'{name}: {what} failed: {e}')
            self.message.emit(f'{name}: move failed ({e})')
            return False
        if started is False:                  # already at the target: no move, no move-done to wait for
            logger.debug(f'{name}: {what}: already there')
            return False
        state.pending = True
        state.sent_at = self._clock()
        self.move_started.emit(name)
        if not self._timer.isActive():
            self._timer.start()
        return True
