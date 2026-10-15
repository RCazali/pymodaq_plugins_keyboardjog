"""Key names, setup model and key map validation (no PyMoDAQ module needed)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core import keys
from pymodaq_plugins_keyboardjog.core.model import Binding, JogSetup, build_keymap, group_members


@pytest.fixture(autouse=True)
def _qt():
    app()


def test_parse_key_names():
    assert keys.parse_key('Left') == keys.KEY_LEFT
    assert keys.parse_key(' up ') == keys.KEY_UP
    assert keys.parse_key('PgUp') is not None
    assert keys.parse_key('a') == keys.parse_key('A')
    for bad in ('', '   ', 'Ctrl+A', 'Left,Right', 'NotAKey'):
        assert keys.parse_key(bad) is None, bad


def test_key_names_round_trip_and_labels():
    for name in ('Left', 'PgDown', 'Home', 'F2', 'A', 'Del'):
        assert keys.key_name(keys.parse_key(name)) == keys.normalize_key_name(name)
    assert keys.normalize_key_name('pgup') == 'PgUp'
    assert keys.normalize_key_name('nonsense') == 'nonsense'
    assert keys.key_label('Left') == '←' and keys.key_label('Up') == '↑'
    assert keys.key_label('PgUp') == 'PgUp'


def test_reserved_keys():
    for name in ('+', '-', '=', 'Shift', 'Ctrl', 'Tab'):
        key = keys.parse_key(name)
        assert key is None or key in keys.RESERVED_KEYS, name


def test_keymap_pair_and_single():
    setup = JogSetup(bindings=[Binding.pair('X', 'Y'), Binding.single('Z', 'PgDown', 'PgUp')])
    keymap, problems = build_keymap(setup)
    assert not problems
    assert keymap[keys.KEY_LEFT].actuator == 'X' and keymap[keys.KEY_LEFT].direction == -1
    assert keymap[keys.KEY_RIGHT].direction == +1
    assert keymap[keys.KEY_DOWN].actuator == 'Y' and keymap[keys.KEY_DOWN].direction == -1
    assert keymap[keys.KEY_UP].direction == +1
    assert keymap[keys.parse_key('PgUp')].actuator == 'Z'
    assert keymap[keys.parse_key('PgUp')].group == 1


def test_keymap_conflicts_are_reported_and_disabled():
    setup = JogSetup(bindings=[Binding.pair('X', 'Y'), Binding.single('Z', 'Up', 'PgUp'),
                               Binding.single('R', '+', 'Ctrl+R'), Binding.single('', 'A', 'B')])
    keymap, problems = build_keymap(setup)
    assert keys.KEY_UP not in keymap                      # used twice: disabled for both
    assert keys.parse_key('PgUp') in keymap
    assert any("'Up' used several times" in p for p in problems)
    assert any('reserved' in p for p in problems)
    assert any('not a valid key' in p for p in problems)
    assert keys.parse_key('A') not in keymap              # no actuator: ignored, no problem
    assert len(problems) == 3


def test_shown_actuators_include_bound_ones_in_dashboard_order():
    setup = JogSetup(displayed=['C'], bindings=[Binding.single('A', 'PgDown', 'PgUp')])
    assert setup.shown_actuators(['A', 'B', 'C', 'D']) == ['A', 'C']


def test_restricted_to_skips_missing_actuators():
    setup = JogSetup(displayed=['A', 'Gone'], bindings=[Binding.pair('A', 'Gone'), Binding.single('Gone2', 'A', 'B')],
                     steps={'A': 0.1, 'Gone': 2.0})
    restricted, warnings = setup.restricted_to(['A', 'B'])
    assert restricted.displayed == ['A']
    assert len(restricted.bindings) == 1
    assert restricted.bindings[0].axes[0].actuator == 'A' and restricted.bindings[0].axes[1].actuator == ''
    assert restricted.steps == {'A': 0.1}
    assert len(warnings) == 3
    assert setup.displayed == ['A', 'Gone']               # the original is untouched


def test_group_members():
    setup = JogSetup(bindings=[Binding.pair('X', 'Y'), Binding.single('Z', 'PgDown', 'PgUp')])
    assert group_members(setup, 0) == ['X', 'Y']
    assert group_members(setup, 1) == ['Z']
    assert group_members(setup, -1) == []
