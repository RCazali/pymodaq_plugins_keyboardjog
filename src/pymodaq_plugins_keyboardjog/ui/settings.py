"""Settings tree of the extension (a PyMoDAQ / pyqtgraph Parameter tree) and its conversion to / from a JogSetup.

The tree is the editor of the setup: ``read_setup`` builds the JogSetup the controller uses from it, ``write_setup``
fills it from a loaded setup. Its dynamic parts (one group per actuator of the Dashboard, one group per extra keys)
are rebuilt by the functions below.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from pymodaq_gui.parameter import Parameter

from ..core.keys import MOVE_KEY_SETS, WASD, normalize_key_name
from ..core.model import AUTO, AXES, HIDDEN, PAIR_CHOICES, ExtraKeys, JogSetup, number_label, number_of

KEY_TIP = ("Key name, e.g. PgUp, PgDown, Home, End, Ins, Del, F2... (no modifiers; the digits, the movement keys, "
           "'+', '-', '=', Shift, Ctrl and Tab are reserved)")
PAIR_TIP = ("Number key (1..9, 0) selecting this actuator. Two actuators with the same number form a pair, moved "
            "together: one horizontal, one vertical. auto: a number of its own, the first free one. hidden: not in "
            "the window")
HEADLESS_TIP = ('Its value is not shown (e.g. a picomotor without encoder): its moves are only seen in the history; '
                'its name turns orange while it moves')
AXIS_TIP = ('horizontal: moved by the left / right keys (A / D or Q / D, arrows). '
            'vertical: moved by the down / up keys (S / W or S / Z, arrows)')
CONTINUOUS_TIP = ('off: one key press = one step. on: steps repeated while the key is held, each one once the '
                  'previous move is done (Shift = step x10, Ctrl = step /10 while held)')

GENERAL_NAMES = ('move_keys', 'step_factor', 'always_on_top', 'show_history', 'min_interval_ms',
                 'stop_on_focus_loss', 'move_timeout_s')


def settings_params() -> list:
    return [
        {'title': 'Setup', 'name': 'setup', 'type': 'group', 'children': [
            {'title': 'Current:', 'name': 'current', 'type': 'str', 'value': '', 'readonly': True,
             'tip': 'Name of the loaded setup (* = modified since loaded / saved)'},
            {'title': 'Saved setups:', 'name': 'saved', 'type': 'list', 'limits': [''], 'value': ''},
            {'title': 'Load', 'name': 'load', 'type': 'action', 'tip': 'Load the setup selected above'},
            {'title': 'Save', 'name': 'save', 'type': 'action', 'tip': 'Save the current setup under its name'},
            {'title': 'New name:', 'name': 'new_name', 'type': 'str', 'value': ''},
            {'title': 'Save as', 'name': 'save_as', 'type': 'action',
             'tip': 'Save the current configuration under the new name'},
            {'title': 'Delete', 'name': 'delete', 'type': 'action', 'tip': 'Delete the setup selected above'},
        ]},
        {'title': 'Problems:', 'name': 'problems', 'type': 'text', 'value': '', 'readonly': True, 'visible': False},
        {'title': 'Actuators', 'name': 'actuators', 'type': 'group', 'children': [],
         'tip': 'Pair number, keys, step, motion mode and display of each actuator of the Dashboard'},
        {'title': 'Motion', 'name': 'general', 'type': 'group', 'children': [
            {'title': 'Move keys:', 'name': 'move_keys', 'type': 'list', 'limits': list(MOVE_KEY_SETS),
             'value': WASD, 'tip': 'Keys moving the selection. wasd: the W A S D keys by their position on the '
                                   'keyboard (Z Q S D on an AZERTY keyboard). arrows: the arrow keys. both.'},
            {'title': 'Step factor:', 'name': 'step_factor', 'type': 'float', 'value': 10.0, 'min': 1.01,
             'tip': "The '+' key multiplies the step by this factor, the '-' key divides it"},
            {'title': 'Min. interval (ms):', 'name': 'min_interval_ms', 'type': 'int', 'value': 0, 'min': 0,
             'tip': 'Continuous mode: minimum time between the end of a step and the next one'},
            {'title': 'Stop on focus loss:', 'name': 'stop_on_focus_loss', 'type': 'bool', 'value': True,
             'tip': 'Stop the actuators moved by this window when it loses the keyboard focus'},
            {'title': 'Move timeout (s):', 'name': 'move_timeout_s', 'type': 'float', 'value': 10.0, 'min': 0.5,
             'tip': 'An actuator whose move-done signal does not arrive within this time accepts new steps again'},
            {'title': 'Always on top:', 'name': 'always_on_top', 'type': 'bool', 'value': True},
            {'title': 'Show history:', 'name': 'show_history', 'type': 'bool', 'value': False,
             'tip': 'History of the moves of the selected group (also the graph button of the window)'},
        ]},
        {'title': 'Extra keys', 'name': 'extra', 'type': 'group', 'expanded': False, 'children': [
            {'title': 'Add extra keys', 'name': 'add', 'type': 'action',
             'tip': 'Two keys of your choice that always move an actuator, whatever the selection '
                    '(e.g. PgDown / PgUp for a focus)'},
        ]},
    ]


# ---------------------------------------------------------------------------------------------- actuators
def fill_actuators(settings: Parameter, names: Sequence[str], units: Dict[str, str], setup: JogSetup):
    group = settings.child('actuators')
    group.clearChildren()
    for i, name in enumerate(names):
        number = setup.number(name)
        pair = HIDDEN if name in setup.hidden else number_label(number) if number else AUTO
        group.addChild({'title': name, 'name': f'act{i:02d}', 'type': 'group', 'expanded': False, 'children': [
            {'title': 'Pair:', 'name': 'pair', 'type': 'list', 'limits': list(PAIR_CHOICES), 'value': pair,
             'tip': PAIR_TIP},
            {'title': 'Keys:', 'name': 'axis', 'type': 'list', 'limits': list(AXES), 'value': setup.axis(name),
             'tip': AXIS_TIP},
            {'title': 'Step:', 'name': 'step', 'type': 'float', 'value': setup.step(name), 'min': 1e-12,
             'suffix': units.get(name, ''), 'decimals': 6},
            {'title': 'Continuous:', 'name': 'continuous', 'type': 'bool', 'value': setup.is_continuous(name),
             'tip': CONTINUOUS_TIP},
            {'title': 'Headless:', 'name': 'headless', 'type': 'bool', 'value': setup.is_headless(name),
             'tip': HEADLESS_TIP},
        ]})


def actuator_group(settings: Parameter, name: str) -> Optional[Parameter]:
    for child in settings.child('actuators').children():
        if child.title() == name:
            return child
    return None


def set_actuator_value(settings: Parameter, name: str, child: str, value) -> bool:
    """Set one setting of an actuator, True if it changed"""
    group = actuator_group(settings, name)
    if group is None or group.child(child).value() == value:
        return False
    group.child(child).setValue(value)
    return True


def set_step_value(settings: Parameter, name: str, value: float):
    set_actuator_value(settings, name, 'step', value)


# ---------------------------------------------------------------------------------------------- extra keys
def extra_groups(settings: Parameter) -> List[Parameter]:
    return [c for c in settings.child('extra').children() if c.type() == 'group']


def _next_extra_name(settings: Parameter) -> str:
    used = {c.name() for c in settings.child('extra').children()}
    i = 0
    while f'x{i:02d}' in used:
        i += 1
    return f'x{i:02d}'


def add_extra_keys(settings: Parameter, extra: ExtraKeys, names: Sequence[str],
                   on_remove: Callable[[Parameter], None] = None) -> Parameter:
    actuator = extra.actuator if extra.actuator in names else ''
    group = settings.child('extra').addChild({
        'title': f'Extra keys {len(extra_groups(settings)) + 1}', 'name': _next_extra_name(settings), 'type': 'group',
        'children': [
            {'title': 'Actuator:', 'name': 'actuator', 'type': 'list', 'limits': [''] + list(names),
             'value': actuator},
            {'title': 'Key -:', 'name': 'minus', 'type': 'str', 'value': extra.key_minus, 'tip': KEY_TIP},
            {'title': 'Key +:', 'name': 'plus', 'type': 'str', 'value': extra.key_plus, 'tip': KEY_TIP},
            {'title': 'Remove', 'name': 'remove', 'type': 'action'},
        ]})
    if on_remove is not None:
        group.child('remove').sigActivated.connect(lambda *_: on_remove(group))
    return group


def set_extra_keys(settings: Parameter, extra_keys: Sequence[ExtraKeys], names: Sequence[str],
                   on_remove: Callable[[Parameter], None] = None):
    for group in extra_groups(settings):
        group.remove()
    for extra in extra_keys:
        add_extra_keys(settings, extra, names, on_remove)


def set_problems(settings: Parameter, problems: Sequence[str]):
    param = settings.child('problems')
    param.setValue('\n'.join(problems))
    param.setOpts(visible=bool(problems))


# ---------------------------------------------------------------------------------------------- setup <-> tree
def read_setup(settings: Parameter) -> JogSetup:
    """The setup described by the tree (pair names are not in the tree: the caller adds them)"""
    general = settings.child('general')
    setup = JogSetup(**{name: general.child(name).value() for name in GENERAL_NAMES})
    for group in settings.child('actuators').children():
        name = group.title()
        if group.child('continuous').value():
            setup.continuous.append(name)
        if group.child('headless').value():
            setup.headless.append(name)
        setup.steps[name] = float(group.child('step').value())
        pair = group.child('pair').value()
        number = number_of(pair)
        if number is not None:
            setup.pair_numbers[name] = number
        elif pair == HIDDEN:
            setup.hidden.append(name)
        setup.axes[name] = group.child('axis').value()
    for group in extra_groups(settings):
        setup.extra_keys.append(ExtraKeys(group.child('actuator').value() or '',
                                          normalize_key_name(group.child('minus').value()),
                                          normalize_key_name(group.child('plus').value())))
    return setup


def write_setup(settings: Parameter, setup: JogSetup, names: Sequence[str], units: Dict[str, str],
                on_remove: Callable[[Parameter], None] = None):
    general = settings.child('general')
    for name in GENERAL_NAMES:
        general.child(name).setValue(getattr(setup, name))
    fill_actuators(settings, names, units, setup)
    set_extra_keys(settings, setup.extra_keys, names, on_remove)


def set_saved_setups(settings: Parameter, names: Sequence[str], current: str = ''):
    saved = settings.child('setup', 'saved')
    limits = list(names) or ['']
    saved.setLimits(limits)
    saved.setValue(current if current in limits else limits[0])
