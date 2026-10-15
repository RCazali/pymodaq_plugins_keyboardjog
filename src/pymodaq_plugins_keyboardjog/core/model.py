"""The configuration of the extension (a *setup*) as plain data, independent of Qt widgets.

Keyboard model:

* the actuators of the main view form numbered **groups**: one group per actuator, except the actuators the user
  put together in a **pair**. One group is **selected** (keys 1..9 or a click); the arrow keys move it: Left / Right
  the first actuator, Down / Up the second one of a pair (both arrow pairs move a single actuator); ``+`` / ``-``
  scale its steps;
* **extra keys** bind an actuator to two keys of the user's choice, active whatever the selection.

A setup holds the displayed actuators, the pairs, the extra keys, the step size of each actuator and the options.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from .actions import MoveAction
from .keys import ARROW_KEYS, RESERVED_KEYS, key_name, parse_key

STEP_MODE = 'step'
CONTINUOUS_MODE = 'continuous'
MOTION_MODES = (STEP_MODE, CONTINUOUS_MODE)

PAIR = 'pair'
SINGLE = 'single'

DEFAULT_STEP = 1.0


@dataclass
class AxisBinding:
    """One actuator, with its two keys for an extra binding (unused in a pair: the arrows move the pairs)"""
    actuator: str = ''
    key_minus: str = ''
    key_plus: str = ''


@dataclass
class Binding:
    """A pair of actuators (one group moved with the arrows) or a single actuator on extra keys"""
    kind: str = SINGLE
    axes: List[AxisBinding] = field(default_factory=list)

    @classmethod
    def pair(cls, x: str = '', y: str = '') -> 'Binding':
        return cls(PAIR, [AxisBinding(x), AxisBinding(y)])

    @classmethod
    def single(cls, actuator: str = '', key_minus: str = '', key_plus: str = '') -> 'Binding':
        return cls(SINGLE, [AxisBinding(actuator, key_minus, key_plus)])

    def actuators(self) -> List[str]:
        return [a.actuator for a in self.axes if a.actuator]


@dataclass
class JogSetup:
    """The complete configuration of the extension, saved / loaded as a named setup"""
    displayed: List[str] = field(default_factory=list)
    bindings: List[Binding] = field(default_factory=list)
    steps: Dict[str, float] = field(default_factory=dict)
    motion_mode: str = STEP_MODE
    step_factor: float = 10.0
    always_on_top: bool = True
    min_interval_ms: int = 0
    stop_on_focus_loss: bool = True
    move_timeout_s: float = 10.0

    @property
    def pairs(self) -> List[Binding]:
        return [b for b in self.bindings if b.kind == PAIR]

    @property
    def extra_keys(self) -> List[Binding]:
        return [b for b in self.bindings if b.kind == SINGLE]

    def bound_actuators(self) -> List[str]:
        out = []
        for b in self.bindings:
            for name in b.actuators():
                if name not in out:
                    out.append(name)
        return out

    def shown_actuators(self, order: Iterable[str]) -> List[str]:
        """Actuators of the main view, in the dashboard order: the displayed ones and every bound one"""
        wanted = set(self.displayed) | set(self.bound_actuators())
        return [name for name in order if name in wanted]

    def step(self, actuator: str) -> float:
        return float(self.steps.get(actuator, DEFAULT_STEP))

    def restricted_to(self, present: Sequence[str]) -> Tuple['JogSetup', List[str]]:
        """Copy keeping only the actuators present in the dashboard, with a message for each skipped item"""
        present = set(present)
        warnings = []
        missing_displayed = [a for a in self.displayed if a not in present]
        if missing_displayed:
            warnings.append(f"not in the dashboard, not displayed: {', '.join(missing_displayed)}")
        bindings = []
        for b in self.bindings:
            axes = []
            for axis in b.axes:
                if axis.actuator and axis.actuator not in present:
                    what = 'pair' if b.kind == PAIR else 'extra keys'
                    warnings.append(f"{what} of '{axis.actuator}' skipped: not in the dashboard")
                    axes.append(AxisBinding('', axis.key_minus, axis.key_plus))
                else:
                    axes.append(AxisBinding(axis.actuator, axis.key_minus, axis.key_plus))
            if any(a.actuator for a in axes):
                bindings.append(Binding(b.kind, axes))
        setup = JogSetup(**{**self.__dict__,
                            'displayed': [a for a in self.displayed if a in present],
                            'bindings': bindings,
                            'steps': {k: v for k, v in self.steps.items() if k in present}})
        return setup, warnings


def build_groups(setup: JogSetup, order: Sequence[str]) -> Tuple[List[List[str]], List[str]]:
    """The numbered groups of the main view (lists of 1 or 2 actuators, in the dashboard order), and the problems"""
    problems = []
    partner: Dict[str, Tuple[str, str]] = {}
    for pair in setup.pairs:
        names = [a.actuator for a in pair.axes]
        if len(names) != 2 or not all(names):
            continue                                     # incomplete pair: its actuator stays a single group
        if names[0] == names[1]:
            problems.append(f"pair '{names[0]}' / '{names[1]}': twice the same actuator")
            continue
        busy = [n for n in names if n in partner]
        if busy:
            problems.append(f"'{busy[0]}' is in several pairs: only the first one is used")
            continue
        partner[names[0]] = partner[names[1]] = (names[0], names[1])
    groups: List[List[str]] = []
    seen = set()
    for name in setup.shown_actuators(order):
        if name in seen:
            continue
        pair = partner.get(name)
        group = list(pair) if pair is not None else [name]
        groups.append(group)
        seen.update(group)
    return groups, problems


def arrow_keymap(group: Sequence[str], group_index: int = -1) -> Dict[int, MoveAction]:
    """Arrow keys -> moves of the selected group: Left/Right the first actuator, Down/Up the second (or the same)"""
    if not group:
        return {}
    x, y = group[0], group[1] if len(group) > 1 else group[0]
    keys = [parse_key(k) for k in ARROW_KEYS]
    return {keys[0]: MoveAction(x, -1, group_index), keys[1]: MoveAction(x, +1, group_index),
            keys[2]: MoveAction(y, -1, group_index), keys[3]: MoveAction(y, +1, group_index)}


def build_keymap(setup: JogSetup) -> Tuple[Dict[int, MoveAction], List[str]]:
    """Key code -> move action of the extra keys, and the problems found

    A key used twice is a conflict: it is reported and disabled for both, so that a key never moves an actuator
    the user did not expect. The arrows, digits, +, -, modifiers and Tab are reserved.
    """
    problems: List[str] = []
    claims: Dict[int, List[MoveAction]] = {}
    for binding in setup.extra_keys:
        for axis in binding.axes:
            if not axis.actuator:
                continue
            for text, direction in ((axis.key_minus, -1), (axis.key_plus, +1)):
                if not (text or '').strip():
                    continue
                key = parse_key(text)
                sign = '-' if direction < 0 else '+'
                if key is None:
                    problems.append(f"'{text}' ({axis.actuator} {sign}) is not a valid key")
                    continue
                if key in RESERVED_KEYS:
                    problems.append(f"'{key_name(key)}' ({axis.actuator} {sign}) is reserved")
                    continue
                claims.setdefault(key, []).append(MoveAction(axis.actuator, direction))
    keymap: Dict[int, MoveAction] = {}
    for key, actions in claims.items():
        if len(actions) > 1:
            who = ', '.join(f"{a.actuator} {'-' if a.direction < 0 else '+'}" for a in actions)
            problems.append(f"'{key_name(key)}' used several times ({who}): disabled")
        else:
            keymap[key] = actions[0]
    return keymap, problems
