"""The configuration of the extension (a *setup*) as plain data, independent of Qt widgets.

A setup holds the displayed actuators, the key bindings (pairs and single actuators), the step size of each
actuator and the general options. ``build_keymap`` turns it into the key -> action table of the keyboard input,
checking that every key is valid and used only once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .actions import MoveAction
from .keys import ARROW_KEYS, RESERVED_KEYS, key_name, parse_key

STEP_MODE = 'step'
CONTINUOUS_MODE = 'continuous'
MOTION_MODES = (STEP_MODE, CONTINUOUS_MODE)

SCOPE_ALL = 'all'
SCOPE_LAST = 'last'
STEP_SCOPES = (SCOPE_ALL, SCOPE_LAST)

PAIR = 'pair'
SINGLE = 'single'

DEFAULT_STEP = 1.0


@dataclass
class AxisBinding:
    """One actuator driven by two keys"""
    actuator: str = ''
    key_minus: str = ''
    key_plus: str = ''


@dataclass
class Binding:
    """A pair (two axes, arrow keys by default) or a single actuator"""
    kind: str = SINGLE
    axes: List[AxisBinding] = field(default_factory=list)

    @classmethod
    def pair(cls, x: str = '', y: str = '', keys: Sequence[str] = ARROW_KEYS) -> 'Binding':
        return cls(PAIR, [AxisBinding(x, keys[0], keys[1]), AxisBinding(y, keys[2], keys[3])])

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
    step_scope: str = SCOPE_ALL
    always_on_top: bool = True
    min_interval_ms: int = 0
    stop_on_focus_loss: bool = True
    move_timeout_s: float = 10.0

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
                    warnings.append(f"binding of '{axis.actuator}' skipped: not in the dashboard")
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


def binding_label(binding: Binding) -> str:
    return ' / '.join(a.actuator or '-' for a in binding.axes)


def build_keymap(setup: JogSetup) -> Tuple[Dict[int, MoveAction], List[str]]:
    """Key code -> move action of every valid binding, and the problems found

    A key used by two bindings is a conflict: it is reported and disabled for both, so that a key never moves
    an actuator the user did not expect.
    """
    problems: List[str] = []
    claims: Dict[int, List[MoveAction]] = {}
    for index, binding in enumerate(setup.bindings):
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
                claims.setdefault(key, []).append(MoveAction(axis.actuator, direction, index))
    keymap: Dict[int, MoveAction] = {}
    for key, actions in claims.items():
        if len(actions) > 1:
            who = ', '.join(f"{a.actuator} {'-' if a.direction < 0 else '+'}" for a in actions)
            problems.append(f"'{key_name(key)}' used several times ({who}): disabled")
        else:
            keymap[key] = actions[0]
    return keymap, problems


def group_members(setup: JogSetup, group: Optional[int]) -> List[str]:
    if group is None or not 0 <= group < len(setup.bindings):
        return []
    return setup.bindings[group].actuators()
