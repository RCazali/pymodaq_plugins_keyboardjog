"""Write a Dashboard configuration with mock actuators to try the extension without hardware.

    python -m pymodaq_plugins_keyboardjog.tools.mock_config [name] [--force]
    python -m pymodaq_plugins_keyboardjog.extensions.keyboard_jog keyboard_jog_mock

    python -m pymodaq_plugins_keyboardjog.tools.mock_config --lab [--force]
    python -m pymodaq_plugins_keyboardjog.extensions.keyboard_jog keyboard_jog_lab

* PyMoDAQ 5.0 / 5.1: a Dashboard **preset** ``<name>.xml`` in the PyMoDAQ preset folder;
* PyMoDAQ >= 5.2: an **experiment** ``<name>.xml`` in the PyMoDAQ experiment folder.

Default content: four ``Mock`` actuators of ``pymodaq_plugins_mock`` (needed): ``Stage X`` / ``Stage Y`` /
``Focus Z`` (axis "Y" of the mock: mm, fine precision) and ``Rotation`` (axis "Theta", degrees), initialized at
startup.

``--lab``: the layout of a laser lab (16 actuators, 10 groups: 6 pairs, 4 single actuators), and its Keyboard Jog
setup ``lab`` (made the last used setup, so it is loaded at startup). The picomotors (OC, End mirror, PM align) are
headless: mock axis "X" (µm, steps of 1), steps of 100. Mixed steps, one continuous actuator, a slow sample stage
(PyMoDAQ 5.1 only: the 5.2+ experiments do not hold the plugin settings).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

DEFAULT_NAME = 'keyboard_jog_mock'
LAB_NAME = 'keyboard_jog_lab'
LAB_SETUP = 'lab'
PLUGIN = 'Mock'
#: (title, mock axis[, tau in ms])
DEFAULT_MOVES: Tuple[Tuple, ...] = (('Stage X', 'Y'), ('Stage Y', 'Y'), ('Focus Z', 'Y'), ('Rotation', 'Theta'))

PICO = 'X'      # µm axis of the mock, precision 1: stands for the steps of a picomotor
MM = 'Y'
#: (group number, pair name, [(title, mock axis, keys, step[, tau ms])], headless)
LAB_GROUPS = (
    (1, 'OC', [('OC H', PICO, 'horizontal', 100), ('OC V', PICO, 'vertical', 100)], True),
    (2, 'End mirror', [('End mirror H', PICO, 'horizontal', 100), ('End mirror V', PICO, 'vertical', 100)], True),
    (3, 'Aperture', [('Aperture X', MM, 'horizontal', 0.1), ('Aperture Y', MM, 'vertical', 0.1)], False),
    (4, 'Gas jet xy', [('Gas jet X', MM, 'horizontal', 0.1), ('Gas jet Y', MM, 'vertical', 0.1)], False),
    (5, 'PM align', [('PM H', PICO, 'horizontal', 100), ('PM V', PICO, 'vertical', 100)], True),
    (6, 'Sample stage', [('Sample X', MM, 'horizontal', 0.01, 1500), ('Sample Y', MM, 'vertical', 0.01, 1500)],
     False),
    (7, '', [('Detuning', MM, 'horizontal', 0.033)], False),
    (8, '', [('Kerr medium', MM, 'horizontal', 1.0)], False),
    (9, '', [('100mm stage', MM, 'horizontal', 0.1)], False),
    (10, '', [('Gas jet Z', MM, 'vertical', 0.1)], False),
)
LAB_CONTINUOUS = ('Kerr medium',)


def lab_moves() -> Tuple[Tuple, ...]:
    return tuple((a[0], a[1]) + tuple(a[4:]) for _, _, actuators, _ in LAB_GROUPS for a in actuators)


def lab_setup():
    """The Keyboard Jog setup of the lab layout"""
    from ..core.model import JogSetup
    setup = JogSetup(continuous=list(LAB_CONTINUOUS), show_history=False)
    for number, name, actuators, headless in LAB_GROUPS:
        if name:
            setup.pair_names[number] = name
        for title, _, axis, step, *_ in actuators:
            setup.pair_numbers[title] = number
            setup.axes[title] = axis
            setup.steps[title] = float(step)
            if headless:
                setup.headless.append(title)
    return setup


def write_lab_setup(config=None) -> Path:
    """Save the 'lab' setup in the setup folder of the extension and make it the last used one"""
    from ..core.setups import SetupStore, default_folder
    store = SetupStore(default_folder(config))
    store.save(LAB_SETUP, lab_setup())
    store.last = LAB_SETUP
    return store.path(LAB_SETUP)


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


def _set_move(move, title: str, axis: str, tau_ms: Optional[int] = None):
    move.child('name').setValue(title)
    module_name = _find(move, 'module_name')     # none in an experiment: it has no plugin settings
    if module_name is not None:
        module_name.setValue(title)
    p = _find(move, 'axis')
    if p is not None:
        p.setValue(axis)
    tau = _find(move, 'tau')
    if tau is not None and tau_ms is not None:
        tau.setValue(tau_ms)
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
    for move in moves:
        p.child('Moves').addNew((PLUGIN,))
        _set_move(p.child('Moves').children()[-1], *move)
    _fix_none_values(p)
    return p


def build_experiment_52(name: str, moves: Sequence[Tuple[str, str]]):
    from pymodaq_gui.parameter import Parameter
    from pymodaq.utils.managers.experiment.experiment_manager import ExperimentManager
    from pymodaq.utils.managers.modules.utils import ModuleType
    p = Parameter.create(title='Preset', name='Preset', type='group', children=ExperimentManager.params)
    acts = p.child(ModuleType.Actuator.value)
    for move in moves:
        acts.addNew((PLUGIN,))
        _set_move(acts.children()[-1], *move)
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
    parser.add_argument('name', nargs='?', default=None)
    parser.add_argument('--force', action='store_true', help='replace an existing preset / experiment')
    parser.add_argument('--lab', action='store_true', help='laser lab layout (16 actuators) and its setup')
    args = parser.parse_args(argv)
    from qtpy import QtWidgets
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])  # noqa: F841 (Parameters)
    name = args.name or (LAB_NAME if args.lab else DEFAULT_NAME)
    moves = lab_moves() if args.lab else DEFAULT_MOVES
    try:
        print(f'Dashboard configuration written: {write_mock_config(name, moves, overwrite=args.force)}')
    except FileExistsError as e:
        print(e)
    if args.lab:
        from ..utils import Config
        print(f"Keyboard Jog setup '{LAB_SETUP}' written (loaded at startup): {write_lab_setup(Config())}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
