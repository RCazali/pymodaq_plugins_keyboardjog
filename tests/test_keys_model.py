"""Key names, setup model, groups and key map validation (no PyMoDAQ module needed)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core import keys
from pymodaq_plugins_keyboardjog.core.model import Binding, Group, JogSetup, build_groups, build_keymap, direction_map


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


def test_movement_keys():
    d = keys.direction_of
    w, a, z, q = (keys.parse_key(k) for k in 'WAZQ')
    # letters when no physical key position is known (macOS, synthetic events)
    assert d(w, 0, 'wasd', 'darwin') == keys.UP and d(a, 0, 'wasd', 'win32') == keys.LEFT
    # physical position on Windows / Linux: the Z key of an AZERTY keyboard is where W is on QWERTY
    assert d(z, 0x11, 'wasd', 'win32') == keys.UP and d(q, 0x1E, 'wasd', 'win32') == keys.LEFT
    assert d(w, 0x2C, 'wasd', 'win32') is None                  # the W letter of AZERTY is elsewhere
    assert d(z, 25, 'wasd', 'linux') == keys.UP
    assert d(keys.KEY_LEFT, 0, 'wasd') is None and d(keys.KEY_LEFT, 0, 'arrows') == keys.LEFT
    assert d(w, 0, 'arrows', 'darwin') is None
    assert d(keys.KEY_UP, 0, 'both') == keys.UP and d(w, 0, 'both', 'darwin') == keys.UP
    assert keys.wasd_letters(azerty=True)[keys.UP] == 'Z'
    assert keys.movement_reserved_keys('wasd', azerty=False) == {w, a, keys.parse_key('S'), keys.parse_key('D')}
    assert keys.movement_reserved_keys('arrows') == frozenset()


def test_default_groups_one_per_actuator():
    setup = JogSetup(displayed=['A', 'B', 'C'])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D'])
    assert [g.actuators for g in groups] == [['A'], ['B'], ['C']] and not problems


def test_pairs_make_one_named_group_at_the_place_of_their_first_member():
    setup = JogSetup(displayed=['A', 'C'], bindings=[Binding.pair('D', 'B', 'Stage'), Binding.pair('E', 'F')])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D', 'E', 'F'])
    assert [g.actuators for g in groups] == [['A'], ['D', 'B'], ['C'], ['E', 'F']]
    assert groups[1].name == 'Stage' and groups[3].name == 'E / F'      # default name
    assert groups[1].is_pair and not groups[0].is_pair
    assert not problems


def test_pair_problems():
    setup = JogSetup(bindings=[Binding.pair('A', 'B'), Binding.pair('B', 'C'), Binding.pair('D', 'D'),
                               Binding.pair('E', '')])
    groups, problems = build_groups(setup, ['A', 'B', 'C', 'D', 'E'])
    assert [g.actuators for g in groups] == [['A', 'B'], ['C'], ['D'], ['E']]
    assert len(problems) == 2


def test_direction_map():
    pair = direction_map(Group(['X', 'Y']), 0)
    assert (pair[keys.LEFT].actuator, pair[keys.LEFT].direction) == ('X', -1)
    assert (pair[keys.RIGHT].actuator, pair[keys.RIGHT].direction) == ('X', +1)
    assert (pair[keys.DOWN].actuator, pair[keys.DOWN].direction) == ('Y', -1)
    assert (pair[keys.UP].actuator, pair[keys.UP].direction) == ('Y', +1)
    single = direction_map(Group(['Z']))
    assert {a.actuator for a in single.values()} == {'Z'}
    assert single[keys.UP].direction == +1 and single[keys.LEFT].direction == -1
    assert direction_map(None) == {}


def test_extra_keys_cannot_use_the_movement_keys():
    setup = JogSetup(bindings=[Binding.single('Z', 'A', 'B')])
    keymap, problems = build_keymap(setup, keys.movement_reserved_keys('wasd', azerty=False))
    assert keys.parse_key('A') not in keymap and keys.parse_key('B') in keymap
    assert any('reserved' in p for p in problems)


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
