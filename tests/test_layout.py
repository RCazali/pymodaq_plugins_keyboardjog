"""Main view layout (one line per group, columns of at most 5 lines) and the lab mock layout (no PyMoDAQ module)."""
import pytest

from helpers import app
from pymodaq_plugins_keyboardjog.core.input import KeyboardInput
from pymodaq_plugins_keyboardjog.core.model import build_groups
from pymodaq_plugins_keyboardjog.tools.mock_config import lab_moves, lab_setup
from pymodaq_plugins_keyboardjog.ui.panel import GroupRow, JogPanel


@pytest.fixture
def lab():
    app()
    names = [m[0] for m in lab_moves()]
    setup = lab_setup()
    groups, problems = build_groups(setup, names)
    return names, setup, groups, problems


def rows_of(groups, setup):
    return [GroupRow(i, g.label, g.title, g.horizontal, g.vertical, {a: 'mm' for a in g.actuators},
                     {a for a in g.actuators if setup.is_headless(a)}) for i, g in enumerate(groups)]


def test_lab_layout_10_groups(lab):
    names, setup, groups, problems = lab
    assert len(names) == 16 and not problems
    assert [g.label for g in groups] == ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
    assert [g.title for g in groups][:3] == ['OC', 'End mirror', 'Aperture']
    assert sum(g.is_pair for g in groups) == 6
    assert groups[9].vertical == 'Gas jet Z' and groups[9].horizontal is None
    assert set(setup.headless) == {'OC H', 'OC V', 'End mirror H', 'End mirror V', 'PM H', 'PM V'}
    assert setup.continuous == ['Kerr medium']


def test_one_line_per_group_in_two_columns_of_five(lab):
    names, setup, groups, _ = lab
    panel = JogPanel(KeyboardInput())
    panel.set_rows(rows_of(groups, setup))
    assert panel.line_count() == 10
    assert [panel.line_position(i) for i in range(10)] == [(i % 5, i // 5) for i in range(10)]
    for name in names:
        panel.set_step(name, setup.step(name))
        panel.set_value(name, 12.3456)
    assert panel.value_text('OC H') == ''                 # headless: no value
    assert panel.value_text('Aperture X') == '12.346'     # step 0.1: 3 decimals
    assert panel.value_text('Sample Y') == '12.3456'      # step 0.01: 4 decimals
    panel.set_rows(rows_of(groups[:6], setup))            # 6 groups: 3 + 3
    assert [panel.line_position(i) for i in range(6)] == [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)]
    panel.set_rows(rows_of(groups[:4], setup))            # 4 groups: one column
    assert [panel.line_position(i)[1] for i in range(4)] == [0, 0, 0, 0]
