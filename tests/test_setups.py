"""Setup persistence (PyMoDAQ ioxml files)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core.model import HORIZONTAL, VERTICAL, ExtraKeys, JogSetup
from pymodaq_plugins_keyboardjog.core.setups import (SetupStore, clean_name, setup_from_parameter,
                                                     setup_to_parameter)


@pytest.fixture(autouse=True)
def _qt():
    app()


def sample_setup():
    return JogSetup(displayed=['Stage X', 'Rotation µ'], continuous=['Stage Y'],
                    pair_numbers={'Stage X': 3, 'Stage Y': 3, 'Focus Z': 10},
                    axes={'Stage X': HORIZONTAL, 'Stage Y': VERTICAL, 'Focus Z': VERTICAL},
                    pair_names={3: 'Sample'}, extra_keys=[ExtraKeys('Focus Z', 'PgDown', 'PgUp')],
                    steps={'Stage X': 0.001, 'Stage Y': 2.5, 'Focus Z': 1e-5},
                    step_factor=5.0, always_on_top=False, show_history=True, min_interval_ms=120,
                    stop_on_focus_loss=False, move_timeout_s=3.0)


def test_parameter_round_trip():
    setup = sample_setup()
    assert setup_from_parameter(setup_to_parameter(setup)) == setup


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
    assert setup.pair_numbers == {} and setup.axes == {} and setup.steps == {} and setup.displayed == []


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
        {'name': 'steps', 'type': 'group', 'children': [{'name': 's00', 'type': 'group', 'children': [
            {'name': 'actuator', 'type': 'str', 'value': 'X'}, {'name': 'step', 'type': 'float', 'value': 0.2}]}]},
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
    assert setup.displayed == ['R'] and setup.steps == {'X': 0.2} and setup.step_factor == 4.0
    assert setup.pair_numbers == {'X': 1, 'Y': 1} and setup.axes == {'X': HORIZONTAL, 'Y': VERTICAL}
    assert setup.pair_names == {1: 'XY'}
    assert setup.extra_keys == [ExtraKeys('Z', 'PgDown', 'PgUp')]
    assert set(setup.continuous) == {'R', 'X', 'Y', 'Z'}
