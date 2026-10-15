"""Key names <-> Qt key codes (works with PyQt5, PyQt6 and PySide6 through qtpy).

Bindings are stored as portable key names (``'Left'``, ``'PgUp'``, ``'A'``...), the names
``QKeySequence`` understands, so that a setup file is readable and can be edited by hand.
"""
from __future__ import annotations

import sys
from typing import Dict, Optional

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

ARROW_CODES = frozenset((KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN))

#: digit keys selecting the group 1..9 (top row and keypad give the same key code)
DIGIT_KEYS = {key_int(getattr(Qt, f'Key_{n}')): n for n in range(1, 10)}

#: keys that cannot be given to an extra binding: the arrows and digits (selected group), the step size keys,
#: the modifiers, and Tab (focus navigation of Qt)
RESERVED_KEYS = STEP_UP_KEYS | STEP_DOWN_KEYS | MODIFIER_KEYS | ARROW_CODES | frozenset(DIGIT_KEYS) | frozenset(
    key_int(k) for k in (Qt.Key_Tab, Qt.Key_Backtab))

#: keys of the selected group: (first axis -, first axis +, second axis -, second axis +)
ARROW_KEYS = ('Left', 'Right', 'Down', 'Up')

# ------------------------------------------------------------------------------------------- movement keys
LEFT, RIGHT, DOWN, UP = 'left', 'right', 'down', 'up'
DIRECTIONS = (LEFT, RIGHT, DOWN, UP)

WASD = 'wasd'
ARROWS = 'arrows'
BOTH = 'both'
MOVE_KEY_SETS = (WASD, ARROWS, BOTH)

_ARROW_DIRECTIONS = {KEY_LEFT: LEFT, KEY_RIGHT: RIGHT, KEY_DOWN: DOWN, KEY_UP: UP}
#: physical positions of W A S D (they read Z Q S D on an AZERTY keyboard)
_WASD_SCAN_CODES = {
    'win32': {0x11: UP, 0x1E: LEFT, 0x1F: DOWN, 0x20: RIGHT},          # set 1 scan codes
    'linux': {25: UP, 38: LEFT, 39: DOWN, 40: RIGHT},                   # X11 / evdev key codes + 8
}
_WASD_KEYS = {key_int(Qt.Key_W): UP, key_int(Qt.Key_A): LEFT, key_int(Qt.Key_S): DOWN, key_int(Qt.Key_D): RIGHT}


def _platform_family(platform: str) -> str:
    return 'linux' if platform.startswith('linux') else platform


def direction_of(key: int, native_scan_code: int = 0, move_keys: str = WASD,
                 platform: str = sys.platform) -> Optional[str]:
    """Movement direction of a key event, None if it is not a movement key of this key set

    WASD keys are recognized by their physical position on Windows and Linux (so the same keys work on QWERTY,
    QWERTZ and AZERTY layouts), by their letter elsewhere.
    """
    if move_keys in (ARROWS, BOTH) and key in _ARROW_DIRECTIONS:
        return _ARROW_DIRECTIONS[key]
    if move_keys in (WASD, BOTH):
        scan_codes = _WASD_SCAN_CODES.get(_platform_family(platform))
        if scan_codes is not None and native_scan_code:
            return scan_codes.get(native_scan_code)
        return _WASD_KEYS.get(key)
    return None


def is_azerty() -> bool:
    """Best guess of an AZERTY keyboard from the input locale (only used for the labels)"""
    try:
        from qtpy import QtGui as _QtGui
        name = _QtGui.QGuiApplication.inputMethod().locale().name()
    except Exception:
        return False
    return name.startswith('fr_') and name not in ('fr_CA', 'fr_CH')


def wasd_letters(azerty: bool = None) -> Dict[str, str]:
    """Letters printed on the WASD keys: {direction: letter}"""
    if azerty is None:
        azerty = is_azerty()
    return {UP: 'Z', LEFT: 'Q', DOWN: 'S', RIGHT: 'D'} if azerty else {UP: 'W', LEFT: 'A', DOWN: 'S', RIGHT: 'D'}


def movement_reserved_keys(move_keys: str, azerty: bool = None) -> frozenset:
    """Key codes the extra keys cannot use with this movement key set"""
    keys = set()
    if move_keys in (WASD, BOTH):
        keys |= {parse_key(letter) for letter in wasd_letters(azerty).values()}
    return frozenset(k for k in keys if k is not None)


def movement_labels(move_keys: str, azerty: bool = None) -> Dict[str, str]:
    """{direction: label} shown in the main view"""
    if move_keys == ARROWS:
        return {LEFT: '←', RIGHT: '→', DOWN: '↓', UP: '↑'}
    return wasd_letters(azerty)


def digit_of(key: int, native_scan_code: int = 0, platform: str = sys.platform) -> Optional[int]:
    """Group number 1..9 of a key event, None if it is not a digit key

    The digit key code is used when the layout gives it (QWERTY, QWERTZ, keypad, Shift + top row on AZERTY). For the
    unshifted top row of the AZERTY layout (& é " ' ( - è _ ç) the physical key position (native scan code) is used
    on Windows and Linux, except for keys the extension already uses (the '-' of the 6 key stays the step key).
    """
    if key in DIGIT_KEYS:
        return DIGIT_KEYS[key]
    if key in STEP_UP_KEYS or key in STEP_DOWN_KEYS or key in MODIFIER_KEYS:
        return None
    if platform == 'win32' and 2 <= native_scan_code <= 10:       # top row 1..9 (set 1 scan codes)
        return native_scan_code - 1
    if platform.startswith('linux') and 10 <= native_scan_code <= 18:   # X11 / evdev key codes + 8
        return native_scan_code - 9
    return None

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
