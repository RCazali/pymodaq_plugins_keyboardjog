"""Named setups saved as XML files with PyMoDAQ's parameter-tree utilities (``pymodaq_gui.parameter.ioxml``).

One file per setup in ``<PyMoDAQ local folder>/KeyboardJog/setups`` (configurable in config_keyboardjog.toml). The
name of the last used setup is kept in ``last_setup.txt`` of the same folder. Reading is tolerant: a missing or
malformed entry takes its default value, so that old or hand-edited files still load. The older setups are
converted: version 1 (pairs as bindings, one motion mode for all) and versions 1-2 (a *display* flag instead of the
*hidden* pair choice).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from pymodaq_gui.parameter import Parameter, ioxml
from pymodaq_utils.logger import set_logger, get_module_name

from .keys import MOVE_KEY_SETS
from .model import AXES, GROUP_NUMBERS, HORIZONTAL, VERTICAL, ExtraKeys, JogSetup

logger = set_logger(get_module_name(__file__))

SETUP_VERSION = 3
LAST_SETUP_FILE = 'last_setup.txt'
EXTENSION_FOLDER = 'KeyboardJog'  # same name as CustomApp.get_local_folder() of PyMoDAQ >= 5.3

_GENERAL = (('all_continuous', 'bool'), ('move_keys', 'str'), ('step_factor', 'float'), ('always_on_top', 'bool'), ('show_history', 'bool'), ('show_keys', 'bool'),
            ('min_interval_ms', 'int'), ('stop_on_focus_loss', 'bool'), ('move_timeout_s', 'float'))


def default_folder(config=None) -> Path:
    from ..utils import config_get
    custom = str(config_get(config, 'setups', 'folder', default='') or '').strip() if config is not None else ''
    if custom:
        return Path(custom)
    from pymodaq_utils.config import get_set_local_dir
    return Path(get_set_local_dir()) / EXTENSION_FOLDER / 'setups'


def clean_name(name: str) -> str:
    """Setup name usable as a file name ('' if nothing is left)"""
    name = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', '_', (name or '').strip())
    return name.strip(' _')


# ---------------------------------------------------------------------------------------------- setup <-> Parameter
def setup_to_parameter(setup: JogSetup) -> Parameter:
    general = [{'name': name, 'type': ptype, 'value': getattr(setup, name)} for name, ptype in _GENERAL]
    actuators = []
    for i, name in enumerate(setup.used_actuators()):
        actuators.append({'name': f'a{i:02d}', 'type': 'group', 'children': [
            {'name': 'actuator', 'type': 'str', 'value': name},
            {'name': 'hidden', 'type': 'bool', 'value': name in setup.hidden},
            {'name': 'headless', 'type': 'bool', 'value': setup.is_headless(name)},
            {'name': 'continuous', 'type': 'bool', 'value': name in setup.continuous},
            {'name': 'step', 'type': 'float', 'value': float(setup.steps.get(name, 0.0))},   # 0: default
            {'name': 'pair', 'type': 'int', 'value': setup.number(name) or 0},              # 0: auto
            {'name': 'axis', 'type': 'str', 'value': setup.axes.get(name, '')},
            {'name': 'label', 'type': 'str', 'value': setup.actuator_names.get(name, '')}]})       # '': not renamed
    names = [{'name': f'p{number:02d}', 'type': 'group', 'children': [
        {'name': 'number', 'type': 'int', 'value': number},
        {'name': 'name', 'type': 'str', 'value': text}]}
        for number, text in sorted(setup.pair_names.items()) if text]
    extra = [{'name': f'x{i:02d}', 'type': 'group', 'children': [
        {'name': 'actuator', 'type': 'str', 'value': e.actuator},
        {'name': 'key_minus', 'type': 'str', 'value': e.key_minus},
        {'name': 'key_plus', 'type': 'str', 'value': e.key_plus}]}
        for i, e in enumerate(setup.extra_keys)]
    return Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'version', 'type': 'int', 'value': SETUP_VERSION},
        {'name': 'general', 'type': 'group', 'children': general},
        {'name': 'actuators', 'type': 'group', 'children': actuators},
        {'name': 'pair_names', 'type': 'group', 'children': names},
        {'name': 'extra_keys', 'type': 'group', 'children': extra},
    ])


def _child(param: Optional[Parameter], name: str) -> Optional[Parameter]:
    if param is None:
        return None
    for child in param.children():
        if child.name() == name:
            return child
    return None


def _children(param: Optional[Parameter], name: str) -> List[Parameter]:
    child = _child(param, name)
    return list(child.children()) if child is not None else []


def _value(param: Optional[Parameter], name: str, default):
    child = _child(param, name)
    if child is None or child.value() is None:
        return default
    value = child.value()
    if isinstance(default, bool) and isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    try:
        return type(default)(value)
    except (TypeError, ValueError):
        return default


def setup_from_parameter(param: Parameter) -> JogSetup:
    defaults = JogSetup()
    general = _child(param, 'general')
    values = {name: _value(general, name, getattr(defaults, name)) for name, _ in _GENERAL}
    if values['move_keys'] not in MOVE_KEY_SETS:
        values['move_keys'] = defaults.move_keys
    if values['step_factor'] <= 1:
        values['step_factor'] = defaults.step_factor
    setup = JogSetup(**values)
    if _child(param, 'actuators') is None and _child(param, 'bindings') is not None:
        _read_version_1(param, setup)
        return setup
    not_displayed = []                       # versions 1-2
    for group in _children(param, 'actuators'):
        name = _value(group, 'actuator', '')
        if not name:
            continue
        if _value(group, 'hidden', False):
            setup.hidden.append(name)
        if _child(group, 'display') is not None and not _value(group, 'display', True):
            not_displayed.append(name)
        if _value(group, 'headless', False):
            setup.headless.append(name)
        if _value(group, 'continuous', False):
            setup.continuous.append(name)
        step = _value(group, 'step', 0.0)
        if step > 0:
            setup.steps[name] = step
        number = _value(group, 'pair', 0)
        if number in GROUP_NUMBERS:
            setup.pair_numbers[name] = number
        axis = _value(group, 'axis', '')
        if axis in AXES:
            setup.axes[name] = axis
        label = _value(group, 'label', '').strip()
        if label:
            setup.actuator_names[name] = label
    for group in _children(param, 'pair_names'):
        number = _value(group, 'number', 0)
        text = _value(group, 'name', '').strip()
        if number in GROUP_NUMBERS and text:
            setup.pair_names[number] = text
    for group in _children(param, 'extra_keys'):
        setup.extra_keys.append(ExtraKeys(_value(group, 'actuator', ''), _value(group, 'key_minus', ''),
                                          _value(group, 'key_plus', '')))
    _hide_not_displayed(setup, not_displayed)
    return setup


def _hide_not_displayed(setup: JogSetup, not_displayed: List[str]):
    """Versions 1-2: an actuator not displayed was hidden, unless it was paired or had extra keys"""
    shown_anyway = set(setup.pair_numbers) | set(setup.key_bound_actuators())
    setup.hidden += [a for a in not_displayed if a not in shown_anyway and a not in setup.hidden]


def _read_version_1(param: Parameter, setup: JogSetup):
    """Setups of version 1: displayed list, steps list, bindings (pairs and single extra keys), one motion mode"""
    displayed = [str(c.value()) for c in _children(param, 'displayed') if c.value()]
    for group in _children(param, 'steps'):
        name = _value(group, 'actuator', '')
        step = _value(group, 'step', 0.0)
        if name and step > 0:
            setup.steps[name] = step
    numbers = iter(GROUP_NUMBERS)
    for group in _children(param, 'bindings'):
        kind = _value(group, 'kind', 'single')
        axes = [(_value(a, 'actuator', ''), _value(a, 'key_minus', ''), _value(a, 'key_plus', ''))
                for a in group.children() if a.name().startswith('axis')]
        if kind == 'pair' and len(axes) == 2:
            number = next(numbers, None)
            if number is None:
                continue
            for (name, _, _), axis in zip(axes, (HORIZONTAL, VERTICAL)):
                if name:
                    setup.pair_numbers[name] = number
                    setup.axes[name] = axis
            if _value(group, 'name', ''):
                setup.pair_names[number] = _value(group, 'name', '')
        elif kind == 'single' and len(axes) == 1:
            setup.extra_keys.append(ExtraKeys(*axes[0]))
        else:
            logger.warning(f'malformed binding {group.name()} ignored')
    if _value(_child(param, 'general'), 'motion_mode', 'step') == 'continuous':
        setup.continuous = list(dict.fromkeys(setup.used_actuators() + displayed))
    # the steps list held every actuator of the dashboard: the ones not displayed were hidden
    _hide_not_displayed(setup, [a for a in setup.steps if a not in displayed])


# ---------------------------------------------------------------------------------------------- setup <-> dict
def setup_to_dict(setup: JogSetup) -> dict:
    """JSON-compatible copy of a setup, for an application storing it in its own files (e.g. Laser Control presets)"""
    return {'version': SETUP_VERSION,
            'general': {name: getattr(setup, name) for name, _ in _GENERAL},
            'hidden': list(setup.hidden), 'headless': list(setup.headless), 'continuous': list(setup.continuous),
            'steps': {k: float(v) for k, v in setup.steps.items()},
            'pair_numbers': {k: int(v) for k, v in setup.pair_numbers.items()},
            'axes': dict(setup.axes),
            'pair_names': {str(k): v for k, v in setup.pair_names.items() if v},
            'actuator_names': {k: v for k, v in setup.actuator_names.items() if v},
            'extra_keys': [{'actuator': e.actuator, 'key_minus': e.key_minus, 'key_plus': e.key_plus}
                           for e in setup.extra_keys]}


def setup_from_dict(data: dict) -> JogSetup:
    """Setup from setup_to_dict; tolerant like the XML reading: a missing or malformed entry takes its default"""
    data = data if isinstance(data, dict) else {}
    defaults = JogSetup()
    general = data.get('general') if isinstance(data.get('general'), dict) else {}
    values = {}
    for name, _ in _GENERAL:
        default = getattr(defaults, name)
        try:
            values[name] = type(default)(general.get(name, default))
        except (TypeError, ValueError):
            values[name] = default
    if values['move_keys'] not in MOVE_KEY_SETS:
        values['move_keys'] = defaults.move_keys
    if values['step_factor'] <= 1:
        values['step_factor'] = defaults.step_factor
    setup = JogSetup(**values)

    def names(key) -> List[str]:
        items = data.get(key)
        return [str(n) for n in items if n] if isinstance(items, list) else []

    def mapping(key) -> dict:
        items = data.get(key)
        return items if isinstance(items, dict) else {}

    setup.hidden, setup.headless, setup.continuous = names('hidden'), names('headless'), names('continuous')
    for name, step in mapping('steps').items():
        try:
            if float(step) > 0:
                setup.steps[str(name)] = float(step)
        except (TypeError, ValueError):
            pass
    for name, number in mapping('pair_numbers').items():
        try:
            if int(number) in GROUP_NUMBERS:
                setup.pair_numbers[str(name)] = int(number)
        except (TypeError, ValueError):
            pass
    setup.axes = {str(k): v for k, v in mapping('axes').items() if v in AXES}
    for number, text in mapping('pair_names').items():
        try:
            if int(number) in GROUP_NUMBERS and str(text).strip():
                setup.pair_names[int(number)] = str(text).strip()
        except (TypeError, ValueError):
            pass
    setup.actuator_names = {str(k): str(v).strip() for k, v in mapping('actuator_names').items()
                            if v is not None and str(v).strip()}
    for extra in data.get('extra_keys') or []:
        if isinstance(extra, dict):
            setup.extra_keys.append(ExtraKeys(str(extra.get('actuator', '') or ''), str(extra.get('key_minus', '') or ''),
                                              str(extra.get('key_plus', '') or '')))
    return setup


# ---------------------------------------------------------------------------------------------- store
class SetupStore:
    """The named setups of a folder"""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def names(self) -> List[str]:
        return sorted((p.stem for p in self.folder.glob('*.xml')), key=str.lower)

    def path(self, name: str) -> Path:
        return self.folder / f'{clean_name(name)}.xml'

    def exists(self, name: str) -> bool:
        return bool(clean_name(name)) and self.path(name).is_file()

    def save(self, name: str, setup: JogSetup) -> str:
        name = clean_name(name)
        if not name:
            raise ValueError('a setup needs a name')
        ioxml.parameter_to_xml_file(setup_to_parameter(setup), self.folder / name, overwrite=True)
        return name

    def load(self, name: str) -> JogSetup:
        path = self.path(name)
        if not path.is_file():
            raise FileNotFoundError(f"no setup named '{name}'")
        children = ioxml.XML_file_to_parameter(path)
        return setup_from_parameter(Parameter.create(name='keyboard_jog_setup', type='group', children=children))

    def delete(self, name: str):
        path = self.path(name)
        if path.is_file():
            path.unlink()
        if self.last == clean_name(name):
            self.last = ''

    @property
    def last(self) -> str:
        try:
            return (self.folder / LAST_SETUP_FILE).read_text(encoding='utf-8').strip()
        except OSError:
            return ''

    @last.setter
    def last(self, name: str):
        try:
            (self.folder / LAST_SETUP_FILE).write_text(clean_name(name), encoding='utf-8')
        except OSError as e:
            logger.warning(f'cannot remember the last setup: {e}')
