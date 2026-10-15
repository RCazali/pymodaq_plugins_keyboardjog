"""Write a Dashboard configuration with mock actuators to try the extension without hardware.

    python -m pymodaq_plugins_keyboardjog.tools.mock_config [name] [--force]
    python -m pymodaq_plugins_keyboardjog.extensions.keyboard_jog keyboard_jog_mock

* PyMoDAQ 5.0 / 5.1: a Dashboard **preset** ``<name>.xml`` in the PyMoDAQ preset folder;
* PyMoDAQ >= 5.2: an **experiment** ``<name>.xml`` in the PyMoDAQ experiment folder.

Content: four ``Mock`` actuators of ``pymodaq_plugins_mock`` (needed): ``Stage X`` / ``Stage Y`` / ``Focus Z``
(axis "Y" of the mock: mm, fine precision) and ``Rotation`` (axis "Theta", degrees), initialized at startup.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

DEFAULT_NAME = 'keyboard_jog_mock'
PLUGIN = 'Mock'
#: (title, mock axis)
DEFAULT_MOVES: Tuple[Tuple[str, str], ...] = (('Stage X', 'Y'), ('Stage Y', 'Y'), ('Focus Z', 'Y'),
                                              ('Rotation', 'Theta'))


def is_pymodaq_52() -> bool:
    """PyMoDAQ >= 5.2 replaced the Dashboard presets by experiments"""
    try:
        import pymodaq.utils.managers.experiment.experiment_manager  # noqa: F401
        return True
    except ImportError:
        return False


def _find(param, name: str):
    for child in param.children():
        if child.name() == name:
            return child
        found = _find(child, name)
        if found is not None:
            return found
    return None


def _fix_none_values(param):
    """Give the parameters created without value the default of the preset editor (else they load as None)"""
    for child in param.children():
        if child.type() != 'group' and child.opts.get('value', None) is None:
            if child.type() in ('bool', 'bool_push', 'led', 'led_push'):
                child.setValue(False)
            elif child.type() == 'list':
                limits = child.opts.get('limits') or []
                values = list(limits.values()) if isinstance(limits, dict) else list(limits)
                if values:
                    child.setValue(values[0])
        _fix_none_values(child)


def _set_move(move, title: str, axis: str):
    move.child('name').setValue(title)
    module_name = _find(move, 'module_name')     # none in an experiment: it has no plugin settings
    if module_name is not None:
        module_name.setValue(title)
    p = _find(move, 'axis')
    if p is not None:
        p.setValue(axis)
    init = _find(move, 'init')
    if init is not None:
        init.setValue(True)


def build_preset_51(name: str, moves: Sequence[Tuple[str, str]]):
    from pymodaq_gui.parameter import Parameter
    import pymodaq.utils.managers.preset_manager_utils  # noqa: F401  registers groupmove / groupdet
    p = Parameter.create(title='Preset', name='Preset', type='group', children=[
        {'title': 'Filename:', 'name': 'filename', 'type': 'str', 'value': name},
        {'title': 'Model Settings:', 'name': 'model_settings', 'type': 'group', 'visible': False, 'children': []},
        {'title': 'Moves:', 'name': 'Moves', 'type': 'groupmove'},
        {'title': 'Detectors:', 'name': 'Detectors', 'type': 'groupdet'}])
    for title, axis in moves:
        p.child('Moves').addNew((PLUGIN,))
        _set_move(p.child('Moves').children()[-1], title, axis)
    _fix_none_values(p)
    return p


def build_experiment_52(name: str, moves: Sequence[Tuple[str, str]]):
    from pymodaq_gui.parameter import Parameter
    from pymodaq.utils.managers.experiment.experiment_manager import ExperimentManager
    from pymodaq.utils.managers.modules.utils import ModuleType
    p = Parameter.create(title='Preset', name='Preset', type='group', children=ExperimentManager.params)
    acts = p.child(ModuleType.Actuator.value)
    for title, axis in moves:
        acts.addNew((PLUGIN,))
        _set_move(acts.children()[-1], title, axis)
    _fix_none_values(p)
    return p


def target_path(name: str = DEFAULT_NAME) -> Path:
    if is_pymodaq_52():
        from pymodaq.utils.config import get_set_experiment_path
        return Path(get_set_experiment_path()).joinpath(f'{name}.xml')
    from pymodaq.utils.config import get_set_preset_path
    return Path(get_set_preset_path()).joinpath(f'{name}.xml')


def write_mock_config(name: str = DEFAULT_NAME, moves: Sequence[Tuple[str, str]] = DEFAULT_MOVES,
                      overwrite: bool = False) -> Path:
    from pymodaq_gui.parameter import ioxml
    path = target_path(name)
    if path.exists() and not overwrite:
        raise FileExistsError(f'{path} already exists (use --force to replace it)')
    p = build_experiment_52(name, moves) if is_pymodaq_52() else build_preset_51(name, moves)
    ioxml.parameter_to_xml_file(p, path.with_suffix(''), overwrite=True)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('name', nargs='?', default=DEFAULT_NAME)
    parser.add_argument('--force', action='store_true', help='replace an existing preset / experiment')
    args = parser.parse_args(argv)
    from qtpy import QtWidgets
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])  # noqa: F841 (Parameters)
    try:
        print(f'Dashboard configuration written: {write_mock_config(args.name, overwrite=args.force)}')
    except FileExistsError as e:
        print(e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
