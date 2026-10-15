"""Key names, setup model, groups and key map validation (no PyMoDAQ module needed)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core import keys
from pymodaq_plugins_keyboardjog.core.model import Binding, JogSetup, arrow_keymap, build_groups, build_keymap


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
    for name in ('+', '-', '=', 'Shift', 'Ctrl', 'Tab', 'Left', 'Up', '1', '9'):
        key = keys.parse_key(name)
        assert key is None or key in keys.RESERVED_KEYS, name


def test_digits():
    assert keys.digit_of(keys.parse_key('1')) == 1
    assert keys.digit_of(keys.parse_key('9')) == 9
    assert keys.digit_of(keys.parse_key('0')) is None
    assert keys.digit_of(keys.parse_key('A')) is None
    # AZERTY top row without Shift: 'é' on the physical 2 key
    e_acute = keys.parse_key('É') or 0xc9
    assert keys.digit_of(e_acute, native_scan_code=3, platform='win32') == 2
    assert keys.digit_of(e_acute, native_scan_code=11, platform='linux') == 2
    assert keys.digit_of(e_acute, native_scan_code=3, platform='darwin') is None
    # the '-' of the AZERTY 6 key stays the step key
    assert keys.digit_of(keys.parse_key('-'), native_scan_code=7, platform='win32') is None
    assert keys.digit_of(keys.parse_key('A'), native_scan_code=30, platform='win32') is None


def test_default_groups_one_per_actuator():
    setup = JogSetup(displayed=['A', 'B', 'C'])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D'])
    assert groups == [['A'], ['B'], ['C']] and not problems


def test_pairs_make_one_group_at_the_place_of_their_first_member():
    setup = JogSetup(displayed=['A', 'C'], bindings=[Binding.pair('D', 'B')])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D'])
    assert groups == [['A'], ['D', 'B'], ['C']]
    assert not problems


def test_pair_problems():
    setup = JogSetup(bindings=[Binding.pair('A', 'B'), Binding.pair('B', 'C'), Binding.pair('D', 'D'),
                               Binding.pair('E', '')])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D', 'E'])
    assert groups == [['A', 'B'], ['C'], ['D'], ['E']]
    assert len(problems) == 2


def test_arrow_keymap():
    pair = arrow_keymap(['X', 'Y'], 0)
    assert (pair[keys.KEY_LEFT].actuator, pair[keys.KEY_LEFT].direction) == ('X', -1)
    assert (pair[keys.KEY_RIGHT].actuator, pair[keys.KEY_RIGHT].direction) == ('X', +1)
    assert (pair[keys.KEY_DOWN].actuator, pair[keys.KEY_DOWN].direction) == ('Y', -1)
    assert (pair[keys.KEY_UP].actuator, pair[keys.KEY_UP].direction) == ('Y', +1)
    single = arrow_keymap(['Z'])
    assert {a.actuator for a in single.values()} == {'Z'}
    assert single[keys.KEY_UP].direction == +1 and single[keys.KEY_LEFT].direction == -1
    assert arrow_keymap([]) == {}


def test_extra_keys_keymap_and_conflicts():
    setup = JogSetup(bindings=[Binding.pair('X', 'Y'), Binding.single('Z', 'PgDown', 'PgUp'),
                               Binding.single('W', 'Home', 'PgUp'), Binding.single('R', '+', 'Ctrl+R'),
                               Binding.single('Q', 'Left', '5'), Binding.single('', 'A', 'B')])
    keymap, problems = build_keymap(setup)
    assert keymap[keys.parse_key('PgDown')].actuator == 'Z'
    assert keys.parse_key('PgUp') not in keymap                 # used twice: disabled for both
    assert keys.parse_key('Home') in keymap
    assert keys.KEY_LEFT not in keymap and keys.parse_key('A') not in keymap
    assert any("'PgUp' used several times" in p for p in problems)
    assert sum('reserved' in p for p in problems) == 3          # '+', 'Left', '5'
    assert any('not a valid key' in p for p in problems)
    assert len(problems) == 5


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
