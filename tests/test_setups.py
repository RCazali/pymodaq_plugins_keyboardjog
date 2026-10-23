"""Setup persistence (PyMoDAQ ioxml files)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core.model import HORIZONTAL, VERTICAL, ExtraKeys, JogSetup
from pymodaq_plugins_keyboardjog.core.setups import (SetupStore, clean_name, setup_from_dict, setup_from_parameter,
                                                     setup_to_dict, setup_to_parameter)


@pytest.fixture(autouse=True)
def _qt():
    app()


def sample_setup():
    return JogSetup(hidden=['Rotation µ'], headless=['Stage X'], continuous=['Stage Y'],
                    pair_numbers={'Stage X': 3, 'Stage Y': 3, 'Focus Z': 10},
                    axes={'Stage X': HORIZONTAL, 'Stage Y': VERTICAL, 'Focus Z': VERTICAL},
                    pair_names={3: 'Sample'}, actuator_names={'Focus Z': 'Focus µ', 'Stage X': 'X'}, extra_keys=[ExtraKeys('Focus Z', 'PgDown', 'PgUp')],
                    steps={'Stage X': 0.001, 'Stage Y': 2.5, 'Focus Z': 1e-5},
                    slow_speeds={'Stage Y': 0.1}, fast_speeds={'Stage Y': 2.0, 'Focus Z': 1e-3},
                    inverted=['Focus Z'],
                    all_continuous=True, step_factor=5.0, always_on_top=False, show_history=True, min_interval_ms=120,
                    stop_on_focus_loss=False, move_timeout_s=3.0)


def test_parameter_round_trip():
    setup = sample_setup()
    assert setup_from_parameter(setup_to_parameter(setup)) == setup


def test_dict_round_trip():
    """Setup stored by an embedding application (Laser Control preset): JSON round trip, tolerant reading"""
    import json
    setup = sample_setup()
    assert setup_from_dict(json.loads(json.dumps(setup_to_dict(setup)))) == setup
    assert setup_from_dict({}) == JogSetup()
    broken = setup_from_dict({'general': {'step_factor': 'x', 'move_keys': 'nope'}, 'steps': {'A': 'bad', 'B': -1},
                              'pair_numbers': {'A': 42, 'B': 2}, 'axes': {'A': 'diagonal'}, 'extra_keys': ['x']})
    assert broken.step_factor == 10.0 and broken.move_keys == JogSetup().move_keys
    assert broken.steps == {} and broken.pair_numbers == {'B': 2} and broken.axes == {} and broken.extra_keys == []


def test_store_save_load_delete(tmp_path):
    store = SetupStore(tmp_path / 'setups')
    assert store.names() == []
    setup = sample_setup()
    assert store.save('Bench 1', setup) == 'Bench 1'
    store.save('alignment', JogSetup())
    assert store.names() == ['alignment', 'Bench 1']
    assert store.load('Bench 1') == setup
    assert store.load('alignment') == JogSetup()
    store.last = 'Bench 1'
    assert SetupStore(tmp_path / 'setups').last == 'Bench 1'
    store.delete('Bench 1')
    assert store.names() == ['alignment']
    assert store.last == ''
    with pytest.raises(FileNotFoundError):
        store.load('Bench 1')


def test_names_are_cleaned():
    assert clean_name(' my/setup:v2.1 ') == 'my_setup_v2_1'
    assert clean_name('../..') == ''
    with pytest.raises(ValueError):
        SetupStore.save(SetupStore.__new__(SetupStore), '  ', JogSetup())


def test_tolerant_loading(tmp_path):
    """Unknown values take their default, malformed entries are dropped"""
    from pymodaq_gui.parameter import Parameter, ioxml
    p = Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'general', 'type': 'group', 'children': [
            {'name': 'move_keys', 'type': 'str', 'value': 'joystick'},
            {'name': 'step_factor', 'type': 'float', 'value': 0.5}]},
        {'name': 'actuators', 'type': 'group', 'children': [
            {'name': 'a00', 'type': 'group', 'children': [
                {'name': 'actuator', 'type': 'str', 'value': 'X'},
                {'name': 'pair', 'type': 'int', 'value': 42},
                {'name': 'axis', 'type': 'str', 'value': 'diagonal'}]},
            {'name': 'a01', 'type': 'group', 'children': [{'name': 'step', 'type': 'float', 'value': 2.0}]}]}])
    ioxml.parameter_to_xml_file(p, tmp_path / 'odd', overwrite=True)
    setup = SetupStore(tmp_path).load('odd')
    assert setup.move_keys == 'wasd' and setup.step_factor == 10.0
    assert setup.pair_numbers == {} and setup.axes == {} and setup.steps == {} and setup.hidden == []


def test_version_1_setups_are_converted(tmp_path):
    """Version 1: pairs as bindings, extra keys as single bindings, one motion mode for all"""
    from pymodaq_gui.parameter import Parameter, ioxml

    def axis(name, minus='', plus=''):
        return [{'name': 'actuator', 'type': 'str', 'value': name},
                {'name': 'key_minus', 'type': 'str', 'value': minus},
                {'name': 'key_plus', 'type': 'str', 'value': plus}]

    p = Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'version', 'type': 'int', 'value': 1},
        {'name': 'general', 'type': 'group', 'children': [
            {'name': 'motion_mode', 'type': 'str', 'value': 'continuous'},
            {'name': 'step_factor', 'type': 'float', 'value': 4.0}]},
        {'name': 'displayed', 'type': 'group', 'children': [{'name': 'a00', 'type': 'str', 'value': 'R'}]},
        {'name': 'steps', 'type': 'group', 'children': [
            {'name': 's00', 'type': 'group', 'children': [
                {'name': 'actuator', 'type': 'str', 'value': 'X'}, {'name': 'step', 'type': 'float', 'value': 0.2}]},
            {'name': 's01', 'type': 'group', 'children': [         # not displayed, not bound: hidden
                {'name': 'actuator', 'type': 'str', 'value': 'T'}, {'name': 'step', 'type': 'float', 'value': 1.0}]}]},
        {'name': 'bindings', 'type': 'group', 'children': [
            {'name': 'b00', 'type': 'group', 'children': [
                {'name': 'kind', 'type': 'str', 'value': 'pair'}, {'name': 'name', 'type': 'str', 'value': 'XY'},
                {'name': 'axis0', 'type': 'group', 'children': axis('X')},
                {'name': 'axis1', 'type': 'group', 'children': axis('Y')}]},
            {'name': 'b01', 'type': 'group', 'children': [
                {'name': 'kind', 'type': 'str', 'value': 'single'}, {'name': 'name', 'type': 'str', 'value': ''},
                {'name': 'axis0', 'type': 'group', 'children': axis('Z', 'PgDown', 'PgUp')}]}]}])
    ioxml.parameter_to_xml_file(p, tmp_path / 'v1', overwrite=True)
    setup = SetupStore(tmp_path).load('v1')
    assert setup.hidden == ['T'] and setup.steps == {'X': 0.2, 'T': 1.0} and setup.step_factor == 4.0
    assert setup.pair_numbers == {'X': 1, 'Y': 1} and setup.axes == {'X': HORIZONTAL, 'Y': VERTICAL}
    assert setup.pair_names == {1: 'XY'}
    assert setup.extra_keys == [ExtraKeys('Z', 'PgDown', 'PgUp')]
    assert set(setup.continuous) == {'R', 'X', 'Y', 'Z', 'T'}


def test_version_2_display_flag_is_converted():
    """Version 2: 'display' per actuator; a non-displayed actuator was shown anyway if paired or with extra keys"""
    from pymodaq_gui.parameter import Parameter

    def actuator(i, name, display, pair=0):
        return {'name': f'a{i:02d}', 'type': 'group', 'children': [
            {'name': 'actuator', 'type': 'str', 'value': name}, {'name': 'display', 'type': 'bool', 'value': display},
            {'name': 'pair', 'type': 'int', 'value': pair}]}

    p = Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'version', 'type': 'int', 'value': 2},
        {'name': 'actuators', 'type': 'group', 'children': [
            actuator(0, 'A', True), actuator(1, 'B', False), actuator(2, 'C', False, pair=3),
            actuator(3, 'D', False)]},
        {'name': 'extra_keys', 'type': 'group', 'children': [{'name': 'x00', 'type': 'group', 'children': [
            {'name': 'actuator', 'type': 'str', 'value': 'D'}, {'name': 'key_minus', 'type': 'str', 'value': 'Home'},
            {'name': 'key_plus', 'type': 'str', 'value': 'End'}]}]}])
    setup = setup_from_parameter(p)
    assert setup.hidden == ['B'] and setup.pair_numbers == {'C': 3}


def test_version_3_file_loads_with_default_speeds(tmp_path):
    """Setups saved before the continuous jog (no slow / fast / invert): default speeds, keys not inverted"""
    from pymodaq_gui.parameter import Parameter, ioxml
    param = setup_to_parameter(sample_setup())
    param.child('version').setValue(3)
    for group in param.child('actuators').children():
        for name in ('slow', 'fast', 'invert'):
            group.removeChild(group.child(name))
    ioxml.parameter_to_xml_file(param, tmp_path / 'old', overwrite=True)
    setup = SetupStore(tmp_path).load('old')
    assert setup.slow_speeds == {} and setup.fast_speeds == {} and setup.inverted == []
    assert setup.steps == sample_setup().steps
    assert setup.slow_speed('Stage Y') == 25.0 and setup.fast_speed('Stage Y') == 250.0
