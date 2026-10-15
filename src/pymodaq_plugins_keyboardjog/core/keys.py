"""Key names <-> Qt key codes (works with PyQt5, PyQt6 and PySide6 through qtpy).

Bindings are stored as portable key names (``'Left'``, ``'PgUp'``, ``'A'``...), the names
``QKeySequence`` understands, so that a setup file is readable and can be edited by hand.
"""
from __future__ import annotations

from typing import Optional

from qtpy import QtCore, QtGui

Qt = QtCore.Qt


def key_int(key) -> int:
    """Qt key (int, Qt.Key enum or QKeyCombination) -> int"""
    if hasattr(key, 'key') and callable(key.key):        # Qt6 QKeyCombination
        key = key.key()
    if hasattr(key, 'value'):                              # Qt6 enums
        key = key.value
    return int(key)


KEY_LEFT = key_int(Qt.Key_Left)
KEY_RIGHT = key_int(Qt.Key_Right)
KEY_UP = key_int(Qt.Key_Up)
KEY_DOWN = key_int(Qt.Key_Down)

#: keys changing the step size (``+`` also as ``=``, its unshifted key on US / AZERTY layouts)
STEP_UP_KEYS = frozenset(key_int(k) for k in (Qt.Key_Plus, Qt.Key_Equal))
STEP_DOWN_KEYS = frozenset(key_int(k) for k in (Qt.Key_Minus,))

SHIFT_KEY = key_int(Qt.Key_Shift)
CONTROL_KEY = key_int(Qt.Key_Control)
MODIFIER_KEYS = frozenset(key_int(k) for k in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
                                               Qt.Key_AltGr, Qt.Key_CapsLock))

#: keys that cannot be bound to an actuator: step size keys, modifiers, and Tab (focus navigation of Qt)
RESERVED_KEYS = STEP_UP_KEYS | STEP_DOWN_KEYS | MODIFIER_KEYS | frozenset(
    key_int(k) for k in (Qt.Key_Tab, Qt.Key_Backtab))

#: default keys of a pair: (x-, x+, y-, y+)
ARROW_KEYS = ('Left', 'Right', 'Down', 'Up')

_SYMBOLS = {KEY_LEFT: '←', KEY_RIGHT: '→', KEY_UP: '↑', KEY_DOWN: '↓'}


def _modifier_mask() -> int:
    return key_int(Qt.KeyboardModifierMask)


def parse_key(text: str) -> Optional[int]:
    """Key name -> Qt key code, None if empty, invalid, or a combination (modifiers are not supported)"""
    text = (text or '').strip()
    if not text:
        return None
    seq = QtGui.QKeySequence(text, QtGui.QKeySequence.PortableText)
    if seq.count() != 1:
        return None
    combination = seq[0]
    if hasattr(combination, 'key') and callable(combination.key):          # Qt6
        if key_int(combination.keyboardModifiers()) != 0:
            return None
        key = key_int(combination.key())
    else:                                                                    # Qt5: an int
        if int(combination) & _modifier_mask():
            return None
        key = int(combination)
    if key in (0, key_int(Qt.Key_unknown)):
        return None
    return key


def key_name(key: int) -> str:
    """Qt key code -> portable key name (as written in the settings)"""
    return QtGui.QKeySequence(int(key)).toString(QtGui.QKeySequence.PortableText)


def key_label(text: str) -> str:
    """Short label of a key for the main view (arrows as symbols)"""
    key = parse_key(text)
    if key is None:
        return '?'
    return _SYMBOLS.get(key, key_name(key))


def normalize_key_name(text: str) -> str:
    """'pgup' -> 'PgUp', '' stays '', an invalid name is kept as typed (reported by the validation)"""
    key = parse_key(text)
    return key_name(key) if key is not None else (text or '').strip()
