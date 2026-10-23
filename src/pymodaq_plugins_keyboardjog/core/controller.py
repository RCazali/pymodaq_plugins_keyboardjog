"""Motion controller: applies the move actions to the actuators.

Rules (safety, see the specification):

* keyboard moves are relative steps (``move_rel``) or continuous jogs; the only absolute move is the explicit "go
  back" to a point of the history, after confirmation (``move_to``);
* **no move is ever queued**: for a given actuator the next move is sent only once the previous one is done
  (move-done signal), and never while the actuator is moved by something else; a request arriving while the
  actuator is busy is dropped;
* each actuator is in step mode (one press = one step) or in continuous mode. In continuous mode, an actuator whose
  plugin implements the continuous jog (``port.supports_jog()``) moves **at constant speed while the key is held**,
  as the lab's old alignment GUI: the slow speed, the fast one while Shift is held (slow / 10 with Ctrl), stopped at
  the key release; the others repeat steps while the action is held, each one sent when the previous one is done,
  after an optional minimum interval, as the alignment jog of LaserControl;
* release: a jog is stopped at once; the step repetition stops at once (the step in progress finishes);
* ``release_all`` (focus lost) forgets every held action, **always stops the jogs** (a jog never outlives its key) and
  can stop the actuators moved by step by this extension;
* while a jog runs, a keep-alive is sent every ``ALIVE_PERIOD_S``: the plugin stops the motor when they stop coming
  (frozen window, lost key release);
* an inverted actuator has its - / + keys swapped (both modes).

A move whose move-done never arrives is forgotten after ``move_timeout_s`` (a warning is logged), or ``STOP_GRACE_S``
after this extension stopped it, so that one lost signal does not lock the actuator forever. DAQ_Move then still
reports the move as running (``move_done_bool`` stays False when the plugin times out, or when its ``stop_motion``
does not end with a move-done): this flag is not trusted for that actuator until its next move-done, else every
key would be refused until PyMoDAQ is restarted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from qtpy import QtCore

from pymodaq_utils.logger import set_logger, get_module_name

from .actions import InputSource, MoveAction
from .model import DEFAULT_SPEED_STEPS, DEFAULT_STEP, FAST_FACTOR
from .ports import ActuatorPort

logger = set_logger(get_module_name(__file__))

TICK_MS = 10
STOP_GRACE_S = 1.0     # after a stop sent by this extension: time left to the plugin to signal the move-done
JOG_STOP_GRACE_S = 4.0  # after the stop of a jog (the plugin waits up to 3 s for the motor to stand still)
ALIVE_PERIOD_S = 0.5   # keep-alive of a running jog
CTRL_FACTOR = 10.0     # Ctrl held: slow speed / 10


@dataclass
class AxisState:
    pending: bool = False             # a move sent by this extension is not done yet
    sent_at: float = 0.0
    done_at: float = float('-inf')
    stopped_at: Optional[float] = None    # this extension stopped the pending move
    lost_done: bool = False           # a move-done was lost: the "moving" flag of the module is stale until the next one
    held: List[int] = field(default_factory=list)  # held directions, the last one wins
    jogging: int = 0                  # direction (actuator sign) of the running jog, 0: none
    jog_speed: float = 0.0
    alive_at: float = 0.0             # last keep-alive sent
    jog_stops: int = 0                # stops of jogs whose move-done did not arrive yet
    jog_stopped_at: float = 0.0


class MotionController(QtCore.QObject):
    step_changed = QtCore.Signal(str, float)
    speeds_changed = QtCore.Signal(str, float, float)   # name, slow, fast
    message = QtCore.Signal(str)
    move_started = QtCore.Signal(str)              # a move was sent by this extension
    move_finished = QtCore.Signal(str, object)     # move done (any origin) with the reached value (None: unknown)

    def __init__(self, clock: Callable[[], float] = time.monotonic, parent: QtCore.QObject = None):
        super().__init__(parent)
        self._clock = clock
        self.ports: Dict[str, ActuatorPort] = {}
        self.steps: Dict[str, float] = {}
        self.speeds: Dict[str, Tuple[float, float]] = {}    # name -> (slow, fast) of the continuous jog
        self.inverted = frozenset()
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
        """New set of actuators: everything held is released (the jogs stopped), the steps of the known actuators are
        kept"""
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
                if state.jogging:
                    self._stop_jog(name, state)
        self._continuous = names

    def is_continuous(self, name: str) -> bool:
        return name in self._continuous

    def is_native(self, name: str) -> bool:
        """Continuous mode by the jog of the plugin (constant speed while held)"""
        port = self.ports.get(name)
        if port is None or not self.is_continuous(name):
            return False
        try:
            return bool(port.supports_jog())
        except Exception:
            return False

    def step(self, name: str) -> float:
        return float(self.steps.get(name, DEFAULT_STEP))

    def set_step(self, name: str, value: float):
        value = abs(float(value))
        if value > 0 and value != self.steps.get(name):
            self.steps[name] = value
            self.step_changed.emit(name, value)

    def slow_speed(self, name: str) -> float:
        speeds = self.speeds.get(name)
        return float(speeds[0]) if speeds else DEFAULT_SPEED_STEPS * self.step(name)

    def fast_speed(self, name: str) -> float:
        speeds = self.speeds.get(name)
        return float(speeds[1]) if speeds else FAST_FACTOR * self.slow_speed(name)

    def jog_speed(self, name: str) -> float:
        """Speed of a jog with the modifiers held now: Shift = fast, Ctrl = slow / 10, none = slow"""
        if self.multiplier > 1:
            return self.fast_speed(name)
        if self.multiplier < 1:
            return self.slow_speed(name) / CTRL_FACTOR
        return self.slow_speed(name)

    def set_speeds(self, name: str, slow: float, fast: float):
        slow, fast = abs(float(slow)), abs(float(fast))
        if slow > 0 and fast > 0 and (slow, fast) != self.speeds.get(name):
            self.speeds[name] = (slow, fast)
            self.speeds_changed.emit(name, slow, fast)

    def scale_steps(self, sign: int, factor: float, names: Iterable[str]):
        """Multiply (sign > 0) or divide (sign < 0) the step of the given actuators by factor (the jog speeds for the
        actuators in continuous jog)"""
        factor = float(factor)
        if factor <= 1:
            return
        k = factor if sign > 0 else 1.0 / factor
        for name in names:
            if self.is_native(name):
                self.set_speeds(name, self.slow_speed(name) * k, self.fast_speed(name) * k)
            else:
                self.set_step(name, self.step(name) * k)

    def set_multiplier(self, value: float):
        self.multiplier = float(value)
        for name, state in self._states.items():     # Shift / Ctrl pressed or released while a key is held
            if state.jogging:
                self._jog(name, state)

    def _sign(self, name: str) -> int:
        return -1 if name in self.inverted else 1

    # ------------------------------------------------------------------ actions
    def press(self, action: MoveAction):
        state = self._states.get(action.actuator)
        if state is None:
            return
        if action.direction in state.held:
            state.held.remove(action.direction)
        state.held.append(action.direction)
        if self.is_native(action.actuator):
            if not self._jog(action.actuator, state, report=True):
                state.held.clear()            # refused: pressing again is needed
            return
        continuous = self.is_continuous(action.actuator)
        self._try_step(action.actuator, action.direction, self.multiplier if continuous else 1.0, report=True)
        if continuous:
            self._timer.start()

    def release(self, action: MoveAction):
        state = self._states.get(action.actuator)
        if state is not None and action.direction in state.held:
            state.held.remove(action.direction)
        if state is not None and state.jogging:
            if state.held:                    # the other direction is still held: go that way
                if not self._jog(action.actuator, state):
                    state.held.clear()
                    self._stop_jog(action.actuator, state)
            else:
                self._stop_jog(action.actuator, state)

    def release_all(self, stop: bool = False):
        """Forget every held action and stop the jogs; with ``stop``, also stop the actuators this extension is
        moving by steps"""
        for name, state in self._states.items():
            state.held.clear()
            if state.jogging:
                self._stop_jog(name, state)
            elif stop and state.pending:
                port = self.ports.get(name)
                try:
                    if state.stopped_at is None:
                        state.stopped_at = self._clock()
                    port.stop()
                    logger.info(f'{name}: stopped (keyboard released)')
                except Exception as e:
                    logger.warning(f'{name}: stop failed: {e}')

    def is_busy(self, name: str) -> bool:
        state = self._states.get(name)
        return bool(state is not None and (state.pending or state.jogging or state.jog_stops))

    def is_jogging(self, name: str) -> bool:
        state = self._states.get(name)
        return bool(state is not None and state.jogging)

    def is_held(self, name: str) -> bool:
        state = self._states.get(name)
        return bool(state is not None and state.held)

    def move_to(self, name: str, value: float) -> bool:
        """Absolute move (go back to a point of the history), with the same rules as a step"""
        state = self._states.get(name)
        if state is not None and state.jogging:
            self.message.emit(f'{name} is jogging: release the key first')
            return False
        return self._send(name, lambda port: port.move_abs(float(value)), f'move_abs({value:g})', report=True)

    # ------------------------------------------------------------------ continuous jog
    def _jog(self, name: str, state: AxisState, report: bool = False) -> bool:
        """Start the jog of the last held direction, or change its direction / speed"""
        port = self.ports.get(name)
        if port is None or not state.held:
            return False
        direction = self._sign(name) * state.held[-1]
        speed = self.jog_speed(name)
        if state.jogging == direction and state.jog_speed == speed:
            return True
        if not state.jogging:
            if state.pending:
                if report:
                    self.message.emit(f'{name} is still moving: key ignored')
                return False
            if not port.is_initialized():
                if report:
                    self.message.emit(f'{name} is not initialized')
                return False
            if port.is_moving() and not state.lost_done:
                if report:
                    self.message.emit(f'{name} is moved by something else: key ignored')
                return False
        try:
            port.jog(direction, speed)
        except Exception as e:
            logger.warning(f'{name}: jog failed: {e}')
            self.message.emit(f'{name}: jog failed ({e})')
            return False
        started = not state.jogging
        state.jogging, state.jog_speed = direction, speed
        state.alive_at = self._clock()
        logger.debug(f'{name}: jog {direction * speed:+g}/s')
        if started:
            self.move_started.emit(name)
        if not self._timer.isActive():
            self._timer.start()
        return True

    def _stop_jog(self, name: str, state: AxisState):
        state.jogging, state.jog_speed = 0, 0.0
        state.jog_stops += 1
        state.jog_stopped_at = self._clock()
        try:
            self.ports[name].stop()
        except Exception as e:
            logger.warning(f'{name}: stop of the jog failed: {e}')
        if not self._timer.isActive():
            self._timer.start()

    # ------------------------------------------------------------------ motion
    def on_move_done(self, name: str, value: Optional[float] = None):
        state = self._states.get(name)
        if state is None:
            return
        if state.jog_stops:
            state.jog_stops -= 1              # the end of a jog stopped here
        elif state.jogging:                   # the plugin ended the jog: end of travel, dead man timeout
            state.jogging, state.jog_speed = 0, 0.0
            state.held.clear()
            self.message.emit(f'{name}: continuous move ended by the actuator (end of travel or timeout)')
        if state.pending:
            state.pending = False
            state.done_at = self._clock()
        state.stopped_at = None
        state.lost_done = False
        self.move_finished.emit(name, value)
        if self.is_continuous(name) and state.held and not state.jogging and not self.is_native(name):
            self.tick()

    def _forget_move(self, name: str, state: AxisState, now: float):
        """The move-done of the pending move will not come: release the actuator, stop repeating (the key has to be
        pressed again), read its position again"""
        stopped = state.stopped_at is not None
        state.pending = False
        state.done_at = now
        state.stopped_at = None
        state.lost_done = True
        state.held.clear()
        if stopped:
            logger.info(f'{name}: no move-done after the stop, actuator released')
        else:
            msg = f'{name}: no move-done after {self.move_timeout_s:g} s (target not reached?), actuator released'
            logger.warning(msg)
            self.message.emit(msg)
        self._request_value(name)
        self.move_finished.emit(name, None)

    def _request_value(self, name: str):
        port = self.ports.get(name)
        try:
            port.request_value()
        except Exception as e:  # pragma: no cover - never block the controller for a position request
            logger.debug(f'{name}: position not requested: {e}')

    def tick(self):
        now = self._clock()
        active = False
        for name, state in self._states.items():
            if state.pending and (now - state.sent_at > self.move_timeout_s or
                                  (state.stopped_at is not None and now - state.stopped_at > STOP_GRACE_S)):
                self._forget_move(name, state, now)
            if state.jogging and now - state.alive_at >= ALIVE_PERIOD_S:
                state.alive_at = now
                try:
                    self.ports[name].jog_alive()
                except Exception as e:
                    logger.debug(f'{name}: keep-alive not sent: {e}')
            if state.jog_stops and now - state.jog_stopped_at > JOG_STOP_GRACE_S:
                state.jog_stops = 0            # its move-done is lost: read the position, record the end anyway
                logger.info(f'{name}: no move-done after the stop of the jog')
                self._request_value(name)
                self.move_finished.emit(name, None)
            if (self.is_continuous(name) and state.held and not state.pending and not state.jogging
                    and not self.is_native(name) and now - state.done_at >= self.min_interval_s):
                self._try_step(name, state.held[-1], self.multiplier)
            active = active or state.pending or bool(state.held) or bool(state.jogging) or bool(state.jog_stops)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _try_step(self, name: str, direction: int, multiplier: float, report: bool = False) -> bool:
        delta = self._sign(name) * direction * self.step(name) * multiplier
        return self._send(name, lambda port: port.move_rel(delta), f'move_rel({delta:g})', report)

    def _send(self, name: str, move: Callable[[ActuatorPort], None], what: str, report: bool) -> bool:
        port = self.ports.get(name)
        state = self._states.get(name)
        if port is None or state is None:
            return False
        if state.pending or state.jog_stops:
            if report:
                self.message.emit(f'{name} is still moving: key ignored')
            return False
        if not port.is_initialized():
            if report:
                self.message.emit(f'{name} is not initialized')
            return False
        if port.is_moving():
            if not state.lost_done:
                if report:
                    self.message.emit(f'{name} is moved by something else: key ignored')
                return False
            logger.info(f'{name}: PyMoDAQ still reports the move whose move-done was lost, {what} sent anyway')
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
        state.stopped_at = None
        self.move_started.emit(name)
        if not self._timer.isActive():
            self._timer.start()
        return True
