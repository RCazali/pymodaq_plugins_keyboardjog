"""Keyboard input source: Qt key events -> abstract actions.

Rules (safety):

* the OS auto-repeat events are ignored: the repetition of the continuous mode is driven by the motion controller;
* a key is "held" from its press to its release; ``reset`` (focus lost) forgets every held key at once;
* Shift / Ctrl give a temporary multiplier (x10 / /10), used by the controller in continuous mode only.

The widget owning the keyboard focus calls ``key_press`` / ``key_release`` only while it is armed (green).
"""
from __future__ import annotations

from typing import Dict

from qtpy import QtCore

from .actions import InputSource, MoveAction
from .keys import CONTROL_KEY, MODIFIER_KEYS, SHIFT_KEY, STEP_DOWN_KEYS, STEP_UP_KEYS, digit_of, key_int

Qt = QtCore.Qt


def _scan_code(event) -> int:
    try:
        return int(event.nativeScanCode())
    except (AttributeError, TypeError, ValueError):
        return 0

MODIFIER_FACTOR = 10.0  # fixed by the specification: Shift = step x10, Ctrl = step /10


def modifier_multiplier(event, pressed: bool) -> float:
    """Multiplier given by the modifiers held *after* this key event

    For the events of the modifier keys themselves, ``QKeyEvent.modifiers()`` gives the state before the event
    (Qt toggles the key's own bit), so the state of the key is taken from the event type instead.
    """
    modifiers = event.modifiers()
    key = key_int(event.key())
    shift = pressed if key == SHIFT_KEY else bool(modifiers & Qt.ShiftModifier)
    ctrl = pressed if key == CONTROL_KEY else bool(modifiers & Qt.ControlModifier)
    if shift and not ctrl:
        return MODIFIER_FACTOR
    if ctrl and not shift:
        return 1.0 / MODIFIER_FACTOR
    return 1.0


class KeyboardInput(InputSource):

    def __init__(self, parent: QtCore.QObject = None):
        super().__init__(parent)
        self._keymap: Dict[int, MoveAction] = {}
        self._arrows: Dict[int, MoveAction] = {}
        self._held: Dict[int, MoveAction] = {}
        self._multiplier = 1.0

    @property
    def held(self) -> Dict[int, MoveAction]:
        return dict(self._held)

    @property
    def multiplier(self) -> float:
        return self._multiplier

    def set_keymap(self, keymap: Dict[int, MoveAction]):
        """New extra keys: the keys currently held are released first"""
        self.release_all()
        self._keymap = dict(keymap)

    def set_arrow_map(self, arrows: Dict[int, MoveAction]):
        """Arrow keys of the newly selected group: the arrows currently held are released first"""
        for key in list(self._held):
            if key in self._arrows:
                self.move_released.emit(self._held.pop(key))
        self._arrows = dict(arrows)

    def _action(self, key: int):
        action = self._arrows.get(key)
        return action if action is not None else self._keymap.get(key)

    def handles(self, key: int, scan_code: int = 0) -> bool:
        return (self._action(key) is not None or key in STEP_UP_KEYS or key in STEP_DOWN_KEYS
                or key in MODIFIER_KEYS or digit_of(key, scan_code) is not None)

    def key_press(self, event) -> bool:
        """Process a key press, return True if the key belongs to the extension (event consumed)"""
        key = key_int(event.key())
        scan_code = _scan_code(event)
        if event.isAutoRepeat():
            return self.handles(key, scan_code)
        self._set_multiplier(modifier_multiplier(event, pressed=True))
        if key in STEP_UP_KEYS:
            self.step_scale_requested.emit(+1)
            return True
        if key in STEP_DOWN_KEYS:
            self.step_scale_requested.emit(-1)
            return True
        action = self._action(key)
        if action is not None:
            if key not in self._held:
                self._held[key] = action
                self.move_pressed.emit(action)
            return True
        number = digit_of(key, scan_code)
        if number is not None:
            self.select_requested.emit(number)
            return True
        return key in MODIFIER_KEYS

    def key_release(self, event) -> bool:
        key = key_int(event.key())
        scan_code = _scan_code(event)
        if event.isAutoRepeat():
            return self.handles(key, scan_code)
        self._set_multiplier(modifier_multiplier(event, pressed=False))
        action = self._held.pop(key, None)
        if action is not None:
            self.move_released.emit(action)
            return True
        return self.handles(key, scan_code)

    def release_all(self):
        for action in self._held.values():
            self.move_released.emit(action)
        self._held.clear()

    def reset(self):
        """Focus lost: forget the held keys and the modifiers, ask the controller to stop repeating"""
        self._held.clear()
        self._set_multiplier(1.0)
        self.reset_requested.emit()

    def _set_multiplier(self, value: float):
        if value != self._multiplier:
            self._multiplier = value
            self.multiplier_changed.emit(value)
