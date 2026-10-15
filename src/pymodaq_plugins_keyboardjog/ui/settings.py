"""Settings tree of the extension (a PyMoDAQ / pyqtgraph Parameter tree) and its conversion to / from a JogSetup.

The tree is the editor of the setup: ``read_setup`` builds the JogSetup the controller uses from it, ``write_setup``
fills it from a loaded setup. Its dynamic parts (one group per actuator of the Dashboard, one group per binding)
are rebuilt by the functions below.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Sequence

from pymodaq_gui.parameter import Parameter

from ..core.keys import normalize_key_name
from ..core.model import Binding, JogSetup, MOTION_MODES, PAIR, SINGLE

KEY_TIP = ("Key name, e.g. PgUp, PgDown, Home, End, Ins, Del, A, Z, F2... (no modifiers; the arrows, the digits, "
           "'+', '-', '=', Shift, Ctrl and Tab are reserved)")

GENERAL_NAMES = ('motion_mode', 'step_factor', 'always_on_top', 'min_interval_ms', 'stop_on_focus_loss',
                 'move_timeout_s')


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
        {'title': 'Motion', 'name': 'general', 'type': 'group', 'children': [
            {'title': 'Mode:', 'name': 'motion_mode', 'type': 'list', 'limits': list(MOTION_MODES), 'value': 'step',
             'tip': 'step: one key press = one step. continuous: steps repeated while the key is held '
                    '(Shift = step x10, Ctrl = step /10 while held)'},
            {'title': 'Step factor:', 'name': 'step_factor', 'type': 'float', 'value': 10.0, 'min': 1.01,
             'tip': "The '+' key multiplies the step by this factor, the '-' key divides it"},
            {'title': 'Min. interval (ms):', 'name': 'min_interval_ms', 'type': 'int', 'value': 0, 'min': 0,
             'tip': 'Continuous mode: minimum time between the end of a step and the next one'},
            {'title': 'Stop on focus loss:', 'name': 'stop_on_focus_loss', 'type': 'bool', 'value': True,
             'tip': 'Stop the actuators moved by this window when it loses the keyboard focus'},
            {'title': 'Move timeout (s):', 'name': 'move_timeout_s', 'type': 'float', 'value': 10.0, 'min': 0.5,
             'tip': 'An actuator whose move-done signal does not arrive within this time accepts new steps again'},
            {'title': 'Always on top:', 'name': 'always_on_top', 'type': 'bool', 'value': True},
        ]},
        {'title': 'Actuators (display / step)', 'name': 'actuators', 'type': 'group', 'children': []},
        {'title': 'Pairs and extra keys', 'name': 'bindings', 'type': 'group', 'children': [
            {'title': 'Add pair', 'name': 'add_pair', 'type': 'action',
             'tip': 'Two actuators selected together (one number): Left/Right move the first one, Down/Up the '
                    'second one (e.g. the X and Y of a stage)'},
            {'title': 'Add extra keys', 'name': 'add_single', 'type': 'action',
             'tip': 'Two keys of your choice that always move an actuator, whatever the selection '
                    '(e.g. PgDown / PgUp for a focus)'},
            {'title': 'Problems:', 'name': 'problems', 'type': 'text', 'value': '', 'readonly': True,
             'visible': False},
        ]},
    ]


# ---------------------------------------------------------------------------------------------- actuators
def fill_actuators(settings: Parameter, names: Sequence[str], units: Dict[str, str], setup: JogSetup):
    group = settings.child('actuators')
    group.clearChildren()
    for i, name in enumerate(names):
        group.addChild({'title': name, 'name': f'act{i:02d}', 'type': 'group', 'expanded': False, 'children': [
            {'title': 'Display:', 'name': 'display', 'type': 'bool', 'value': name in setup.displayed},
            {'title': 'Step:', 'name': 'step', 'type': 'float', 'value': setup.step(name), 'min': 1e-12,
             'suffix': units.get(name, ''), 'decimals': 6},
        ]})


def actuator_group(settings: Parameter, name: str):
    for child in settings.child('actuators').children():
        if child.title() == name:
            return child
    return None


# ---------------------------------------------------------------------------------------------- bindings
def binding_groups(settings: Parameter) -> List[Parameter]:
    return [c for c in settings.child('bindings').children() if c.name().startswith('b') and c.type() == 'group']


def _next_binding_name(settings: Parameter) -> str:
    used = {c.name() for c in settings.child('bindings').children()}
    i = 0
    while f'b{i:02d}' in used:
        i += 1
    return f'b{i:02d}'


def add_binding(settings: Parameter, binding: Binding, names: Sequence[str],
                on_remove: Callable[[Parameter], None] = None) -> Parameter:
    limits = [''] + list(names)
    children = [{'title': 'Kind', 'name': 'kind', 'type': 'str', 'value': binding.kind, 'visible': False}]
    labels = ('First (Left/Right)', 'Second (Down/Up)') if binding.kind == PAIR else ('Actuator',)
    for j, axis in enumerate(binding.axes):
        actuator = axis.actuator if axis.actuator in names else ''
        children.append({'title': f'{labels[j]}:', 'name': f'act{j}', 'type': 'list', 'limits': limits,
                         'value': actuator})
        if binding.kind == SINGLE:
            children += [
                {'title': '  key -:', 'name': f'minus{j}', 'type': 'str', 'value': axis.key_minus, 'tip': KEY_TIP},
                {'title': '  key +:', 'name': f'plus{j}', 'type': 'str', 'value': axis.key_plus, 'tip': KEY_TIP},
            ]
    children.append({'title': 'Remove', 'name': 'remove', 'type': 'action'})
    count = sum(1 for g in binding_groups(settings) if g.child('kind').value() == binding.kind) + 1
    group = settings.child('bindings').addChild({
        'title': f"{'Pair' if binding.kind == PAIR else 'Extra keys'} {count}", 'name': _next_binding_name(settings),
        'type': 'group', 'children': children})
    if on_remove is not None:
        group.child('remove').sigActivated.connect(lambda *_: on_remove(group))
    return group


def set_bindings(settings: Parameter, bindings: Sequence[Binding], names: Sequence[str],
                 on_remove: Callable[[Parameter], None] = None):
    for group in binding_groups(settings):
        group.remove()
    for binding in bindings:
        add_binding(settings, binding, names, on_remove)


def set_problems(settings: Parameter, problems: Sequence[str]):
    param = settings.child('bindings', 'problems')
    param.setValue('\n'.join(problems))
    param.setOpts(visible=bool(problems))


# ---------------------------------------------------------------------------------------------- setup <-> tree
def read_setup(settings: Parameter) -> JogSetup:
    general = settings.child('general')
    setup = JogSetup(**{name: general.child(name).value() for name in GENERAL_NAMES})
    for group in settings.child('actuators').children():
        if group.child('display').value():
            setup.displayed.append(group.title())
        setup.steps[group.title()] = float(group.child('step').value())
    for group in binding_groups(settings):
        if group.child('kind').value() == PAIR:
            setup.bindings.append(Binding.pair(group.child('act0').value() or '', group.child('act1').value() or ''))
        else:
            setup.bindings.append(Binding.single(group.child('act0').value() or '',
                                                 normalize_key_name(group.child('minus0').value()),
                                                 normalize_key_name(group.child('plus0').value())))
    return setup


def write_setup(settings: Parameter, setup: JogSetup, names: Sequence[str], units: Dict[str, str],
                on_remove: Callable[[Parameter], None] = None):
    general = settings.child('general')
    for name in GENERAL_NAMES:
        general.child(name).setValue(getattr(setup, name))
    fill_actuators(settings, names, units, setup)
    set_bindings(settings, setup.bindings, names, on_remove)


def set_step_value(settings: Parameter, name: str, value: float):
    group = actuator_group(settings, name)
    if group is not None and group.child('step').value() != value:
        group.child('step').setValue(value)


def set_saved_setups(settings: Parameter, names: Sequence[str], current: str = ''):
    saved = settings.child('setup', 'saved')
    limits = list(names) or ['']
    saved.setLimits(limits)
    saved.setValue(current if current in limits else limits[0])
