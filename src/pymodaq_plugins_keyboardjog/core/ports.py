"""Access to the Dashboard actuators.

**This is the only module touching DAQ_Move objects.** It uses their public API: ``move_rel``,
``move_abs`` (go back to a point of the history), ``stop_motion``, ``get_actuator_value``, the ``current_value_signal`` /
``move_done_signal`` signals and the ``title``, ``units``, ``initialized_state``, ``move_done_bool`` properties.
DAQ_Move handles its own hardware thread, everything here runs in the Qt main thread.

Continuous jog (plugins implementing ``jog``, e.g. those of pymodaq_plugins_hhglab): ``ThreadCommand('jog',
[direction, speed])`` and ``ThreadCommand('jog_alive', [])`` through ``command_hardware`` (PyMoDAQ calls the plugin
method of that name in the hardware thread), stopped by ``stop_motion``. Whether the plugin implements it is read on the
plugin instance (read only, see ``plugin_of``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple

from pymodaq_utils.logger import set_logger, get_module_name

logger = set_logger(get_module_name(__file__))

try:
    from pymodaq_utils.utils import ThreadCommand
except ImportError:  # pragma: no cover - older pymodaq_utils
    from pymodaq.utils.daq_utils import ThreadCommand


def data_to_float(data) -> Optional[float]:
    """DataActuator (or number) -> float, None if not convertible"""
    try:
        if hasattr(data, 'value'):
            return float(data.value())
        return float(data)
    except Exception:
        return None


def plugin_of(module):
    """The plugin instance of a DAQ_Move, living in its hardware thread (read only: capability detection), None if not
    initialized. PyMoDAQ 5.1: ``_hardware_thread.hardware.hardware``; 5.3: the worker registered in
    ``controller_and_thread.thread`` (by title), ``.plugin``"""
    worker = None
    thread = getattr(getattr(module, 'controller_and_thread', None), 'thread', None)
    hardwares = getattr(thread, '__dict__', {}).get('_hardwares') if thread is not None else None
    if isinstance(hardwares, dict):
        worker = hardwares.get(str(getattr(module, 'title', '')))
    if worker is None:
        worker = getattr(getattr(module, '_hardware_thread', None), 'hardware', None)
    return getattr(worker, 'plugin', None) or getattr(worker, 'hardware', None)


class ActuatorPort(ABC):
    """What the motion controller and the main view need from an actuator (implemented by fakes in the tests)"""
    name: str = ''
    on_value: Optional[Callable[[Optional[float]], None]] = None  # new current value
    on_done: Optional[Callable[[Optional[float]], None]] = None   # move done (with the reached value)

    def units(self) -> str:
        return ''

    def is_initialized(self) -> bool:
        return True

    def is_moving(self) -> bool:
        return False

    @abstractmethod
    def move_rel(self, delta: float):
        """Start a relative move, its end is signalled through ``on_done``"""

    def move_abs(self, value: float) -> Optional[bool]:
        """Start an absolute move (go back to a point of the history), its end is signalled through ``on_done``.
        Returns False if no move was started (already at the target: no move-done will come)"""
        raise NotImplementedError(f'{self.name}: no absolute move')  # noqa: PMQ202 optional capability of a port

    @abstractmethod
    def stop(self):
        """Stop the motion"""

    def supports_jog(self) -> bool:
        """The actuator can move continuously at a given speed (``jog``) until ``stop``"""
        return False

    def jog(self, direction: int, speed: float):
        """Start (or change) a continuous move: direction +1 / -1, speed in units / s; its end (``stop``, end of
        travel...) is signalled through ``on_done``"""
        raise NotImplementedError(f'{self.name}: no continuous jog')  # noqa: PMQ202 optional capability of a port

    def jog_alive(self):
        """Keep-alive of a running jog (the plugin stops it when they stop coming)"""

    def request_value(self):
        pass

    def disconnect(self):
        pass


class DAQMovePort(ActuatorPort):
    """Port on a DAQ_Move module of the Dashboard"""

    def __init__(self, module):
        self.module = module
        self.name = str(module.title)
        self.on_value = None
        self.on_done = None
        self._connections: List[Tuple[object, object]] = []
        for signal_name, slot in (('current_value_signal', self._value_slot), ('move_done_signal', self._done_slot)):
            signal = getattr(module, signal_name, None)
            if signal is None:
                logger.warning(f'{self.name}: no {signal_name}')
                continue
            signal.connect(slot)
            self._connections.append((signal, slot))

    def _value_slot(self, data):
        if self.on_value is not None:
            self.on_value(data_to_float(data))

    def _done_slot(self, data):
        value = data_to_float(data)
        if self.on_done is not None:
            self.on_done(value)
        if self.on_value is not None:
            self.on_value(value)

    def disconnect(self):
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._connections = []

    def units(self) -> str:
        try:
            return str(self.module.units or '')
        except Exception:
            return ''

    def is_initialized(self) -> bool:
        try:
            return bool(self.module.initialized_state)
        except Exception:
            return False

    def is_moving(self) -> bool:
        """True while a move (from this extension or from anything else: a scan, the module UI...) is running"""
        try:
            return not bool(self.module.move_done_bool)
        except Exception:
            return False

    def move_rel(self, delta: float):
        self.module.move_rel(float(delta))

    def move_abs(self, value: float) -> Optional[bool]:
        """DAQ_Move ignores a target equal to its current value (no move, no move-done signal); when it accepts the
        move it clears move_done_bool at once"""
        self.module.move_abs(float(value))
        try:
            return not bool(self.module.move_done_bool)
        except Exception:  # pragma: no cover
            return None

    def stop(self):
        self.module.stop_motion()

    def supports_jog(self) -> bool:
        try:
            return self.is_initialized() and callable(getattr(plugin_of(self.module), 'jog', None))
        except Exception:
            return False

    def jog(self, direction: int, speed: float):
        self.module.command_hardware.emit(ThreadCommand('jog', [int(direction), float(speed)]))

    def jog_alive(self):
        self.module.command_hardware.emit(ThreadCommand('jog_alive', []))

    def request_value(self):
        if self.is_initialized():
            self.module.get_actuator_value()


def actuator_modules(modules_manager) -> list:
    """The DAQ_Move modules of the Dashboard (read-only use of the modules manager)"""
    if modules_manager is None:
        return []
    return list(getattr(modules_manager, 'actuators_all', None) or [])


def make_ports(modules: list) -> Dict[str, DAQMovePort]:
    ports: Dict[str, DAQMovePort] = {}
    for module in modules:
        try:
            port = DAQMovePort(module)
        except Exception as e:  # pragma: no cover - never block the extension for one module
            logger.warning(f'actuator {getattr(module, "title", module)} ignored: {e}')
            continue
        ports[port.name] = port
    return ports
