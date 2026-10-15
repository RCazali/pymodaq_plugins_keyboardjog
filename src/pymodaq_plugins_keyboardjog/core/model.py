"""The configuration of the extension (a *setup*) as plain data, independent of Qt widgets.

Keyboard model:

* every actuator has a few settings of its own: **pair** (``hidden``, ``auto``, 1..9, 0), **keys** (horizontal or
  vertical), step size, step or continuous motion, and **headless** (its value is not shown: e.g. a picomotor, whose
  moves are only seen in the history);
* the actuators sharing a pair number form one numbered **group** (a pair: e.g. the X and Y of a stage). An actuator
  left on ``auto`` is a group of its own and takes the first free number; a ``hidden`` one is not in the window at
  all. The number key (1..9, 0) or a click selects a group; the movement keys (W A S D and / or the arrows) move it:
  left / right the *horizontal* actuator, down / up the *vertical* one; ``+`` / ``-`` scale its steps;
* **extra keys** bind a (not hidden) actuator to two keys of the user's choice, active whatever the selection.

A setup holds all of this plus the general options; it is saved / loaded by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .actions import MoveAction
from .keys import DOWN, LEFT, RESERVED_KEYS, RIGHT, UP, WASD, key_name, parse_key

HORIZONTAL = 'horizontal'
VERTICAL = 'vertical'
AXES = (HORIZONTAL, VERTICAL)

AUTO = 'auto'
HIDDEN = 'hidden'
GROUP_NUMBERS = tuple(range(1, 11))       # 10 is the '0' key
PAIR_CHOICES = (HIDDEN, AUTO) + tuple(str(n % 10) for n in GROUP_NUMBERS)

DEFAULT_STEP = 1.0


def number_label(number: Optional[int]) -> str:
    """Group number -> its key ('0' for 10, '' for no number)"""
    if number is None:
        return ''
    return str(number % 10)


def number_of(label) -> Optional[int]:
    """Pair choice ('auto', '1'..'9', '0') -> group number (None for auto / invalid)"""
    text = str(label).strip()
    if not text.isdigit():
        return None
    value = int(text)
    if value == 0:
        return 10
    return value if value in GROUP_NUMBERS else None


@dataclass
class ExtraKeys:
    """Two keys of the user's choice moving one actuator (- / +), whatever the selection"""
    actuator: str = ''
    key_minus: str = ''
    key_plus: str = ''


@dataclass
class JogSetup:
    """The complete configuration of the extension, saved / loaded as a named setup"""
    hidden: List[str] = field(default_factory=list)              # actuators not in the window
    headless: List[str] = field(default_factory=list)            # actuators whose value is not shown
    steps: Dict[str, float] = field(default_factory=dict)
    continuous: List[str] = field(default_factory=list)          # actuators in continuous mode
    pair_numbers: Dict[str, int] = field(default_factory=dict)   # actuator -> 1..10 (absent: auto)
    axes: Dict[str, str] = field(default_factory=dict)           # actuator -> horizontal / vertical
    pair_names: Dict[int, str] = field(default_factory=dict)     # group number -> name of the pair
    extra_keys: List[ExtraKeys] = field(default_factory=list)
    all_continuous: bool = False                                 # every actuator in continuous mode
    move_keys: str = WASD
    step_factor: float = 10.0
    always_on_top: bool = True
    show_history: bool = False
    min_interval_ms: int = 0
    stop_on_focus_loss: bool = True
    move_timeout_s: float = 10.0

    def step(self, actuator: str) -> float:
        return float(self.steps.get(actuator, DEFAULT_STEP))

    def axis(self, actuator: str) -> str:
        axis = self.axes.get(actuator, HORIZONTAL)
        return axis if axis in AXES else HORIZONTAL

    def number(self, actuator: str) -> Optional[int]:
        number = self.pair_numbers.get(actuator)
        return number if number in GROUP_NUMBERS else None

    def is_continuous(self, actuator: str) -> bool:
        """Continuous mode of an actuator: its own choice, or all of them with ``all_continuous``"""
        return self.all_continuous or actuator in self.continuous

    def is_headless(self, actuator: str) -> bool:
        return actuator in self.headless

    def key_bound_actuators(self) -> List[str]:
        out = []
        for extra in self.extra_keys:
            if extra.actuator and extra.actuator not in out:
                out.append(extra.actuator)
        return out

    def shown_actuators(self, order: Iterable[str]) -> List[str]:
        """Actuators of the main view, in the dashboard order: all but the hidden ones"""
        return [name for name in order if name not in self.hidden]

    def used_actuators(self) -> List[str]:
        """Every actuator this setup refers to"""
        out = []
        for name in (list(self.hidden) + list(self.pair_numbers) + self.key_bound_actuators() + list(self.headless)
                     + list(self.continuous) + list(self.axes) + list(self.steps)):
            if name not in out:
                out.append(name)
        return out

    def restricted_to(self, present: Sequence[str]) -> Tuple['JogSetup', List[str]]:
        """Copy keeping only the actuators present in the dashboard, with a message for each skipped item"""
        present = set(present)
        warnings = []
        for name, number in self.pair_numbers.items():
            if name not in present:
                warnings.append(f"pair {number_label(number)}: '{name}' skipped, not in the dashboard")
        extra_keys = []
        for extra in self.extra_keys:
            if extra.actuator and extra.actuator not in present:
                warnings.append(f"extra keys of '{extra.actuator}' skipped: not in the dashboard")
            else:
                extra_keys.append(ExtraKeys(extra.actuator, extra.key_minus, extra.key_plus))
        keep = lambda d: {k: v for k, v in d.items() if k in present}  # noqa: E731
        setup = JogSetup(**{**self.__dict__,
                            'hidden': [a for a in self.hidden if a in present],
                            'headless': [a for a in self.headless if a in present],
                            'steps': keep(self.steps),
                            'continuous': [a for a in self.continuous if a in present],
                            'pair_numbers': keep(self.pair_numbers),
                            'axes': keep(self.axes),
                            'pair_names': dict(self.pair_names),
                            'extra_keys': extra_keys})
        return setup, warnings


@dataclass
class Group:
    """A numbered group of the main view: one actuator, or a pair (actuators sharing a pair number)"""
    actuators: List[str]
    number: Optional[int] = None
    name: str = ''
    horizontal: Optional[str] = None    # moved by left / right
    vertical: Optional[str] = None      # moved by down / up
    explicit: bool = False              # pair number chosen by the user (not auto)

    @property
    def is_pair(self) -> bool:
        return len(self.actuators) >= 2

    @property
    def label(self) -> str:
        return number_label(self.number)

    @property
    def title(self) -> str:
        return self.name or ' / '.join(self.actuators)

    @property
    def moved(self) -> List[str]:
        """The actuators the movement keys move: horizontal first"""
        return [a for a in (self.horizontal, self.vertical) if a]

    def __contains__(self, actuator: str) -> bool:
        return actuator in self.actuators


def build_groups(setup: JogSetup, order: Sequence[str]) -> Tuple[List[Group], List[str]]:
    """The numbered groups of the main view (sorted by number) and the problems found

    The actuators of an explicit number form one group. The others are groups of one actuator numbered with the free
    numbers, in the dashboard order (no number at all once the 10 numbers are taken: click to select them). In a group,
    the first horizontal actuator takes left / right, the first vertical one down / up; any other one is reported.
    """
    problems = []
    shown = setup.shown_actuators(order)
    explicit: Dict[int, List[str]] = {}
    automatic = []
    for name in shown:
        number = setup.number(name)
        if number is None:
            automatic.append(name)
        else:
            explicit.setdefault(number, []).append(name)
    free = [n for n in GROUP_NUMBERS if n not in explicit]
    groups = [Group(names, number, explicit=True) for number, names in explicit.items()]
    groups += [Group([name], free.pop(0) if free else None) for name in automatic]

    for group in groups:
        horizontal = [a for a in group.actuators if setup.axis(a) == HORIZONTAL]
        vertical = [a for a in group.actuators if setup.axis(a) == VERTICAL]
        group.horizontal = horizontal[0] if horizontal else None
        group.vertical = vertical[0] if vertical else None
        for extra, first, keys in [(a, horizontal[0], 'horizontal') for a in horizontal[1:]] + \
                                  [(a, vertical[0], 'vertical') for a in vertical[1:]]:
            problems.append(f"pair {group.label}: '{extra}' and '{first}' are both {keys}: '{extra}' is not moved "
                            f"by the movement keys")
        group.actuators = group.moved + [a for a in group.actuators if a not in group.moved]
        if group.is_pair:
            group.name = setup.pair_names.get(group.number, '').strip()
    groups.sort(key=lambda g: (g.number is None, g.number or 0, order.index(g.actuators[0])))
    return groups, problems


def direction_map(group: Optional[Group], group_index: int = -1) -> Dict[str, MoveAction]:
    """Movement direction -> move of the selected group: left / right its horizontal actuator, down / up its
    vertical one"""
    if group is None:
        return {}
    out = {}
    if group.horizontal:
        out[LEFT] = MoveAction(group.horizontal, -1, group_index)
        out[RIGHT] = MoveAction(group.horizontal, +1, group_index)
    if group.vertical:
        out[DOWN] = MoveAction(group.vertical, -1, group_index)
        out[UP] = MoveAction(group.vertical, +1, group_index)
    return out


def build_keymap(setup: JogSetup, reserved: Iterable[int] = ()) -> Tuple[Dict[int, MoveAction], List[str]]:
    """Key code -> move action of the extra keys, and the problems found

    A key used twice is a conflict: it is reported and disabled for both, so that a key never moves an actuator
    the user did not expect. The arrows, digits, +, -, modifiers, Tab and the given keys (the movement keys) are
    reserved. The extra keys of a hidden actuator are disabled: nothing moves that is not in the window.
    """
    reserved = RESERVED_KEYS | frozenset(reserved)
    problems: List[str] = []
    claims: Dict[int, List[MoveAction]] = {}
    for extra in setup.extra_keys:
        if not extra.actuator:
            continue
        if extra.actuator in setup.hidden:
            problems.append(f"extra keys of '{extra.actuator}' disabled: it is hidden")
            continue
        for text, direction in ((extra.key_minus, -1), (extra.key_plus, +1)):
            if not (text or '').strip():
                continue
            key = parse_key(text)
            sign = '-' if direction < 0 else '+'
            if key is None:
                problems.append(f"'{text}' ({extra.actuator} {sign}) is not a valid key")
                continue
            if key in reserved:
                problems.append(f"'{key_name(key)}' ({extra.actuator} {sign}) is reserved")
                continue
            claims.setdefault(key, []).append(MoveAction(extra.actuator, direction))
    keymap: Dict[int, MoveAction] = {}
    for key, actions in claims.items():
        if len(actions) > 1:
            who = ', '.join(f"{a.actuator} {'-' if a.direction < 0 else '+'}" for a in actions)
            problems.append(f"'{key_name(key)}' used several times ({who}): disabled")
        else:
            keymap[key] = actions[0]
    return keymap, problems
