"""Named setups saved as XML files with PyMoDAQ's parameter-tree utilities (``pymodaq_gui.parameter.ioxml``).

One file per setup in ``<PyMoDAQ local folder>/KeyboardJog/setups`` (configurable in config_keyboardjog.toml). The
name of the last used setup is kept in ``last_setup.txt`` of the same folder. Reading is tolerant: a missing or
malformed entry takes its default value, so that old or hand-edited files still load.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from pymodaq_gui.parameter import Parameter, ioxml
from pymodaq_utils.logger import set_logger, get_module_name

from .keys import MOVE_KEY_SETS
from .model import AxisBinding, Binding, JogSetup, MOTION_MODES, PAIR, SINGLE, STEP_MODE

logger = set_logger(get_module_name(__file__))

SETUP_VERSION = 1
LAST_SETUP_FILE = 'last_setup.txt'
EXTENSION_FOLDER = 'KeyboardJog'  # same name as CustomApp.get_local_folder() of PyMoDAQ >= 5.3

_GENERAL = (('motion_mode', 'str'), ('move_keys', 'str'), ('step_factor', 'float'), ('always_on_top', 'bool'),
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
    displayed = [{'name': f'a{i:02d}', 'type': 'str', 'value': name} for i, name in enumerate(setup.displayed)]
    steps = [{'name': f's{i:02d}', 'type': 'group', 'children': [
        {'name': 'actuator', 'type': 'str', 'value': name},
        {'name': 'step', 'type': 'float', 'value': float(value)}]}
        for i, (name, value) in enumerate(setup.steps.items())]
    bindings = []
    for i, binding in enumerate(setup.bindings):
        axes = [{'name': f'axis{j}', 'type': 'group', 'children': [
            {'name': 'actuator', 'type': 'str', 'value': axis.actuator},
            {'name': 'key_minus', 'type': 'str', 'value': axis.key_minus},
            {'name': 'key_plus', 'type': 'str', 'value': axis.key_plus}]}
            for j, axis in enumerate(binding.axes)]
        bindings.append({'name': f'b{i:02d}', 'type': 'group',
                         'children': [{'name': 'kind', 'type': 'str', 'value': binding.kind},
                                      {'name': 'name', 'type': 'str', 'value': binding.name}] + axes})
    return Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'version', 'type': 'int', 'value': SETUP_VERSION},
        {'name': 'general', 'type': 'group', 'children': general},
        {'name': 'displayed', 'type': 'group', 'children': displayed},
        {'name': 'steps', 'type': 'group', 'children': steps},
        {'name': 'bindings', 'type': 'group', 'children': bindings},
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
    if values['motion_mode'] not in MOTION_MODES:
        values['motion_mode'] = STEP_MODE
    if values['move_keys'] not in MOVE_KEY_SETS:
        values['move_keys'] = defaults.move_keys
    if values['step_factor'] <= 1:
        values['step_factor'] = defaults.step_factor
    displayed = [str(c.value()) for c in _children(param, 'displayed') if c.value()]
    steps = {}
    for group in _children(param, 'steps'):
        name = _value(group, 'actuator', '')
        step = _value(group, 'step', 0.0)
        if name and step > 0:
            steps[name] = step
    bindings = []
    for group in _children(param, 'bindings'):
        kind = _value(group, 'kind', SINGLE)
        axes = [AxisBinding(_value(a, 'actuator', ''), _value(a, 'key_minus', ''), _value(a, 'key_plus', ''))
                for a in group.children() if a.name().startswith('axis')]
        if kind == PAIR and len(axes) == 2 or kind == SINGLE and len(axes) == 1:
            bindings.append(Binding(kind, axes, _value(group, 'name', '')))
        else:
            logger.warning(f'malformed binding {group.name()} ignored')
    return JogSetup(displayed=displayed, bindings=bindings, steps=steps, **values)


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
