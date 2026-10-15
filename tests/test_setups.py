"""Setup persistence (PyMoDAQ ioxml files)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core.model import Binding, JogSetup
from pymodaq_plugins_keyboardjog.core.setups import (SetupStore, clean_name, setup_from_parameter,
                                                     setup_to_parameter)


@pytest.fixture(autouse=True)
def _qt():
    app()


def sample_setup():
    return JogSetup(displayed=['Stage X', 'Rotation µ'], bindings=[Binding.pair('Stage X', 'Stage Y'),
                                                                   Binding.single('Focus Z', 'PgDown', 'PgUp')],
                    steps={'Stage X': 0.001, 'Stage Y': 2.5, 'Focus Z': 1e-5}, motion_mode='continuous',
                    step_factor=5.0, always_on_top=False, min_interval_ms=120,
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
    """Unknown values take their default, malformed bindings are dropped"""
    from pymodaq_gui.parameter import Parameter, ioxml
    p = Parameter.create(name='keyboard_jog_setup', type='group', children=[
        {'name': 'general', 'type': 'group', 'children': [
            {'name': 'motion_mode', 'type': 'str', 'value': 'warp'},
            {'name': 'step_factor', 'type': 'float', 'value': 0.5}]},
        {'name': 'bindings', 'type': 'group', 'children': [
            {'name': 'b00', 'type': 'group', 'children': [{'name': 'kind', 'type': 'str', 'value': 'pair'}]}]}])
    ioxml.parameter_to_xml_file(p, tmp_path / 'odd', overwrite=True)
    setup = SetupStore(tmp_path).load('odd')
    assert setup.motion_mode == 'step' and setup.step_factor == 10.0
    assert setup.bindings == [] and setup.displayed == []
